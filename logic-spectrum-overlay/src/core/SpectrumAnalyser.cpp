#include "SpectrumAnalyser.h"

#include <algorithm>
#include <cmath>

namespace lso
{

static inline float gainToDb (float gain, float floorDb) noexcept
{
    return gain > 1.0e-9f ? std::max (floorDb, 20.0f * std::log10 (gain)) : floorDb;
}

float SpectrumAnalyser::binCentreHz (int index, int numBinsIn, float minHz, float maxHz) noexcept
{
    if (numBinsIn <= 1)
        return minHz;

    const auto t = (float) index / (float) (numBinsIn - 1);
    return minHz * std::pow (maxHz / minHz, t);
}

void SpectrumAnalyser::prepare (double sampleRateIn, int numBinsIn, const AnalyserSettings& settingsIn)
{
    sampleRate = sampleRateIn > 0.0 ? sampleRateIn : 44100.0;
    settings = settingsIn;
    numBins = numBinsIn;
    fftSize = 1 << settings.fftOrder;

    fft = std::make_unique<Fft> (settings.fftOrder);

    fifo.assign ((size_t) kFifoCapacity, 0.0f);
    writePos.store (0, std::memory_order_relaxed);
    lastFramePos = 0;

    window.resize ((size_t) fftSize);
    double windowSum = 0.0;

    for (int i = 0; i < fftSize; ++i)
    {
        // Hann
        const auto w = 0.5 - 0.5 * std::cos (2.0 * M_PI * (double) i / (double) fftSize);
        window[(size_t) i] = (float) w;
        windowSum += w;
    }

    // Scaling such that a full-scale sine at a bin centre reads 0 dBFS.
    windowGain = (float) (2.0 / windowSum);

    workRe.assign ((size_t) fftSize, 0.0f);
    workIm.assign ((size_t) fftSize, 0.0f);
    magnitude.assign ((size_t) (fftSize / 2 + 1), 0.0f);

    frameDb.assign ((size_t) numBins, settings.floorDb);
    smoothedDb.assign ((size_t) numBins, settings.floorDb);

    rebuildBinMapping();
    reset();
}

void SpectrumAnalyser::rebuildBinMapping()
{
    binCentresHz.resize ((size_t) numBins);
    tiltDb.resize ((size_t) numBins);
    binLo.resize ((size_t) numBins);
    binHi.resize ((size_t) numBins);

    const auto fftBinWidth = (float) (sampleRate / (double) fftSize);
    const auto nyquistBin = fftSize / 2;

    for (int i = 0; i < numBins; ++i)
    {
        const auto centre = binCentreHz (i, numBins, settings.minFrequencyHz, settings.maxFrequencyHz);
        binCentresHz[(size_t) i] = centre;

        const auto below = binCentreHz (i - 1, numBins, settings.minFrequencyHz, settings.maxFrequencyHz);
        const auto above = binCentreHz (i + 1, numBins, settings.minFrequencyHz, settings.maxFrequencyHz);

        const auto lowEdge = i == 0 ? centre : std::sqrt (below * centre);
        const auto highEdge = i == numBins - 1 ? centre : std::sqrt (centre * above);

        binLo[(size_t) i] = std::clamp ((int) std::ceil (lowEdge / fftBinWidth), 0, nyquistBin);
        binHi[(size_t) i] = std::clamp ((int) std::floor (highEdge / fftBinWidth), 0, nyquistBin);
    }

    setTiltDbPerOctave (settings.tiltDbPerOctave);
}

void SpectrumAnalyser::setTiltDbPerOctave (float tilt) noexcept
{
    settings.tiltDbPerOctave = tilt;

    for (int i = 0; i < numBins; ++i)
        tiltDb[(size_t) i] = tilt * std::log2 (binCentresHz[(size_t) i] / 1000.0f);
}

void SpectrumAnalyser::reset() noexcept
{
    std::fill (smoothedDb.begin(), smoothedDb.end(), settings.floorDb);
    std::fill (frameDb.begin(), frameDb.end(), settings.floorDb);
    std::fill (fifo.begin(), fifo.end(), 0.0f);
    peakDb = settings.floorDb;
    rmsDb = settings.floorDb;
}

void SpectrumAnalyser::pushSamples (const float* const* channelData, int numChannels, int numSamples) noexcept
{
    if (fifo.empty() || numChannels <= 0 || numSamples <= 0)
        return;

    const auto scale = 1.0f / (float) numChannels;
    auto pos = writePos.load (std::memory_order_relaxed);

    for (int n = 0; n < numSamples; ++n)
    {
        float sum = 0.0f;

        for (int ch = 0; ch < numChannels; ++ch)
            sum += channelData[ch][n];

        fifo[(size_t) ((pos + (uint64_t) n) & kFifoMask)] = sum * scale;
    }

    writePos.store (pos + (uint64_t) numSamples, std::memory_order_release);
}

bool SpectrumAnalyser::process() noexcept
{
    if (fft == nullptr)
        return false;

    const auto pos = writePos.load (std::memory_order_acquire);

    if (pos < (uint64_t) fftSize)
        return false;

    const auto newSamples = pos - lastFramePos;

    if (newSamples < (uint64_t) settings.hopSamples)
        return false;

    const auto elapsedSeconds = (double) newSamples / sampleRate;
    lastFramePos = pos;

    // Always analyse the freshest window; intermediate hops are skipped, which
    // keeps the display current when the analysis thread is called irregularly.
    const auto start = pos - (uint64_t) fftSize;
    float framePeak = 0.0f;
    double sumSquares = 0.0;

    for (int i = 0; i < fftSize; ++i)
    {
        const auto sample = fifo[(size_t) ((start + (uint64_t) i) & kFifoMask)];
        framePeak = std::max (framePeak, std::abs (sample));
        sumSquares += (double) sample * (double) sample;

        workRe[(size_t) i] = sample * window[(size_t) i];
        workIm[(size_t) i] = 0.0f;
    }

    peakDb = gainToDb (framePeak, settings.floorDb);
    rmsDb = gainToDb ((float) std::sqrt (sumSquares / (double) fftSize), settings.floorDb);

    fft->forward (workRe.data(), workIm.data());

    const auto nyquistBin = fftSize / 2;
    const auto fftBinWidth = (float) (sampleRate / (double) fftSize);

    for (int k = 0; k <= nyquistBin; ++k)
        magnitude[(size_t) k] = std::sqrt (workRe[(size_t) k] * workRe[(size_t) k]
                                           + workIm[(size_t) k] * workIm[(size_t) k]) * windowGain;

    // A tone rarely sits exactly on a bin centre, and the window's scalloping
    // loss would then under-read it by up to 1.4 dB. Refining each local
    // maximum with a parabola through its neighbours (in dB) recovers the true
    // peak level, so levels can be compared across tracks and read off the
    // grid. Non-peak bins are left alone.
    for (int k = nyquistBin - 1; k >= 1; --k)
    {
        const auto here = magnitude[(size_t) k];

        if (! (here > magnitude[(size_t) (k - 1)] && here > magnitude[(size_t) (k + 1)]))
            continue;

        const auto a = gainToDb (magnitude[(size_t) (k - 1)], settings.floorDb);
        const auto b = gainToDb (here, settings.floorDb);
        const auto c = gainToDb (magnitude[(size_t) (k + 1)], settings.floorDb);
        const auto curvature = a - 2.0f * b + c;

        if (curvature > -1.0e-6f)
            continue;

        const auto offset = std::clamp (0.5f * (a - c) / curvature, -0.5f, 0.5f);
        const auto refinedDb = b - 0.25f * (a - c) * offset;
        magnitude[(size_t) k] = std::pow (10.0f, refinedDb / 20.0f);
    }

    auto magnitudeAt = [this] (int k) noexcept { return magnitude[(size_t) k]; };

    for (int i = 0; i < numBins; ++i)
    {
        const auto lo = binLo[(size_t) i];
        const auto hi = binHi[(size_t) i];
        float magnitude;

        if (hi >= lo)
        {
            magnitude = 0.0f;

            for (int k = lo; k <= hi; ++k)
                magnitude = std::max (magnitude, magnitudeAt (k));
        }
        else
        {
            // Below the FFT's resolution: interpolate between neighbouring bins.
            const auto exact = binCentresHz[(size_t) i] / fftBinWidth;
            const auto k0 = std::clamp ((int) std::floor (exact), 0, nyquistBin);
            const auto k1 = std::min (k0 + 1, nyquistBin);
            const auto frac = exact - (float) k0;
            magnitude = magnitudeAt (k0) * (1.0f - frac) + magnitudeAt (k1) * frac;
        }

        frameDb[(size_t) i] = gainToDb (magnitude, settings.floorDb) + tiltDb[(size_t) i];
    }

    // Instant attack, exponential release, in the dB domain.
    const auto tau = std::max (0.01f, settings.releaseSeconds);
    const auto releaseCoeff = 1.0f - (float) std::exp (-elapsedSeconds / (double) tau);

    for (int i = 0; i < numBins; ++i)
    {
        auto& smoothed = smoothedDb[(size_t) i];
        const auto target = frameDb[(size_t) i];
        smoothed = target > smoothed ? target : smoothed + (target - smoothed) * releaseCoeff;
    }

    return true;
}

} // namespace lso
