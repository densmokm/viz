#pragma once

#include "Fft.h"

#include <atomic>
#include <cstdint>
#include <memory>
#include <vector>

namespace lso
{

struct AnalyserSettings
{
    int fftOrder = 12;              // 4096-point window (~85 ms at 48 kHz)
    int hopSamples = 1024;          // minimum new samples between frames
    float minFrequencyHz = 20.0f;
    float maxFrequencyHz = 20000.0f;
    float floorDb = -100.0f;
    float releaseSeconds = 0.30f;   // display fall time constant
    float tiltDbPerOctave = 3.0f;   // 3 dB/oct makes pink noise read flat
};

/** Single-producer / single-consumer spectrum analyser.

    The audio thread only ever calls pushSamples(); the analysis thread only
    ever calls process(). No locks and no allocation on either path once
    prepare() has run.
*/
class SpectrumAnalyser
{
public:
    SpectrumAnalyser() = default;

    void prepare (double sampleRateIn, int numBinsIn, const AnalyserSettings& settingsIn);
    void reset() noexcept;

    /** Audio thread: sums channels to mono and stores them. Realtime-safe. */
    void pushSamples (const float* const* channelData, int numChannels, int numSamples) noexcept;

    /** Analysis thread: produces a new frame when enough audio has arrived.
        @returns true if getBinsDb() changed.
    */
    bool process() noexcept;

    const std::vector<float>& getBinsDb() const noexcept { return smoothedDb; }
    const std::vector<float>& getBinCentresHz() const noexcept { return binCentresHz; }

    float getPeakDb() const noexcept { return peakDb; }
    float getRmsDb() const noexcept { return rmsDb; }
    int getNumBins() const noexcept { return numBins; }
    bool isPrepared() const noexcept { return fft != nullptr; }

    void setTiltDbPerOctave (float tilt) noexcept;

    /** Frequency of an output bin, and the reverse mapping, as used by the UI. */
    static float binCentreHz (int index, int numBinsIn, float minHz, float maxHz) noexcept;

private:
    void rebuildBinMapping();

    AnalyserSettings settings;
    double sampleRate = 44100.0;
    int numBins = 0;
    int fftSize = 0;

    std::unique_ptr<Fft> fft;

    // Lock-free mono ring buffer.
    static constexpr int kFifoCapacity = 1 << 15;
    static constexpr uint64_t kFifoMask = kFifoCapacity - 1;
    std::vector<float> fifo;
    std::atomic<uint64_t> writePos { 0 };
    uint64_t lastFramePos = 0;

    std::vector<float> window;
    std::vector<float> workRe, workIm;
    std::vector<float> magnitude;   // per FFT bin, peak-corrected
    std::vector<float> frameDb, smoothedDb, tiltDb, binCentresHz;
    std::vector<int> binLo, binHi;      // FFT bin range feeding each output bin
    float windowGain = 1.0f;

    float peakDb = -120.0f;
    float rmsDb = -120.0f;
};

} // namespace lso
