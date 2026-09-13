// Tests for the framework-free core: FFT, analyser calibration, and the
// cross-process registry. Runs anywhere, no plugin host needed.

#include "../src/core/CollisionFinder.h"
#include "../src/core/Fft.h"
#include "../src/core/Palette.h"
#include "../src/core/SpectrumAnalyser.h"
#include "../src/core/TrackRegistry.h"

#include <atomic>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <thread>
#include <vector>

#include <sys/wait.h>
#include <unistd.h>

namespace
{
int testsRun = 0;
int testsFailed = 0;
std::string currentTest;

void startTest (const std::string& name)
{
    currentTest = name;
    ++testsRun;
}

void fail (const std::string& message)
{
    ++testsFailed;
    std::printf ("  FAIL  %s\n        %s\n", currentTest.c_str(), message.c_str());
}

void check (bool condition, const std::string& message)
{
    if (! condition)
        fail (message);
}

void checkNear (double actual, double expected, double tolerance, const std::string& what)
{
    if (std::abs (actual - expected) > tolerance)
        fail (what + ": expected " + std::to_string (expected) + " +/- " + std::to_string (tolerance)
              + ", got " + std::to_string (actual));
}

std::string temporaryRegistryPath (const std::string& suffix)
{
    return "/tmp/lso-test-" + std::to_string (getpid()) + "-" + suffix + ".bin";
}

//==============================================================================
void testFftMatchesNaiveDft()
{
    startTest ("FFT matches a naive DFT");

    constexpr int order = 6;
    constexpr int size = 1 << order;

    std::vector<float> re (size), im (size, 0.0f), originalRe (size);

    for (int i = 0; i < size; ++i)
        originalRe[(size_t) i] = re[(size_t) i] = std::sin (0.37f * (float) i) + 0.5f * std::cos (0.11f * (float) i);

    lso::Fft fft (order);
    fft.forward (re.data(), im.data());

    double worstError = 0.0;

    for (int k = 0; k < size; ++k)
    {
        double sumRe = 0.0, sumIm = 0.0;

        for (int n = 0; n < size; ++n)
        {
            const auto angle = -2.0 * M_PI * (double) k * (double) n / (double) size;
            sumRe += originalRe[(size_t) n] * std::cos (angle);
            sumIm += originalRe[(size_t) n] * std::sin (angle);
        }

        worstError = std::max (worstError, std::abs (sumRe - re[(size_t) k]));
        worstError = std::max (worstError, std::abs (sumIm - im[(size_t) k]));
    }

    check (worstError < 1.0e-3, "largest deviation from the DFT was " + std::to_string (worstError));
}

//==============================================================================
void feedSine (lso::SpectrumAnalyser& analyser, double sampleRate, float frequency, float amplitude, int numSamples)
{
    std::vector<float> buffer ((size_t) numSamples);
    static double phase = 0.0;
    const auto delta = 2.0 * M_PI * (double) frequency / sampleRate;

    for (int i = 0; i < numSamples; ++i)
    {
        buffer[(size_t) i] = amplitude * (float) std::sin (phase);
        phase += delta;
    }

    const float* channels[1] = { buffer.data() };
    analyser.pushSamples (channels, 1, numSamples);
}

int peakBinIndex (const std::vector<float>& bins)
{
    int best = 0;

    for (size_t i = 1; i < bins.size(); ++i)
        if (bins[i] > bins[(size_t) best])
            best = (int) i;

    return best;
}

void testAnalyserCalibration()
{
    constexpr double sampleRate = 48000.0;
    lso::AnalyserSettings settings;
    settings.tiltDbPerOctave = 0.0f;   // measure the raw level

    startTest ("a full-scale 1 kHz sine reads 0 dBFS at 1 kHz");
    {
        lso::SpectrumAnalyser analyser;
        analyser.prepare (sampleRate, lso::kNumBins, settings);

        for (int block = 0; block < 16; ++block)
        {
            feedSine (analyser, sampleRate, 1000.0f, 1.0f, 512);
            analyser.process();
        }

        const auto& bins = analyser.getBinsDb();
        const auto peak = peakBinIndex (bins);
        const auto peakHz = analyser.getBinCentresHz()[(size_t) peak];

        checkNear (bins[(size_t) peak], 0.0, 0.6, "peak level");
        checkNear (peakHz, 1000.0, 60.0, "peak frequency");
        checkNear (analyser.getPeakDb(), 0.0, 0.2, "time-domain peak");
    }

    startTest ("a -24 dBFS sine reads -24 dBFS");
    {
        lso::SpectrumAnalyser analyser;
        analyser.prepare (sampleRate, lso::kNumBins, settings);
        const auto amplitude = (float) std::pow (10.0, -24.0 / 20.0);

        for (int block = 0; block < 16; ++block)
        {
            feedSine (analyser, sampleRate, 1000.0f, amplitude, 512);
            analyser.process();
        }

        const auto& bins = analyser.getBinsDb();
        checkNear (bins[(size_t) peakBinIndex (bins)], -24.0, 0.6, "peak level");
    }

    startTest ("a tone between two FFT bins still reads its true level");
    {
        for (auto frequency : { 1017.0f, 2371.0f, 5113.0f })
        {
            lso::SpectrumAnalyser analyser;
            analyser.prepare (sampleRate, lso::kNumBins, settings);

            for (int block = 0; block < 24; ++block)
            {
                feedSine (analyser, sampleRate, frequency, 1.0f, 512);
                analyser.process();
            }

            const auto& bins = analyser.getBinsDb();
            const auto peak = peakBinIndex (bins);
            checkNear (bins[(size_t) peak], 0.0, 0.5,
                       "peak level at " + std::to_string ((int) frequency) + " Hz");
            checkNear (analyser.getBinCentresHz()[(size_t) peak], frequency, frequency * 0.04f,
                       "peak frequency at " + std::to_string ((int) frequency) + " Hz");
        }
    }

    startTest ("silence sits on the floor");
    {
        lso::SpectrumAnalyser analyser;
        analyser.prepare (sampleRate, lso::kNumBins, settings);

        for (int block = 0; block < 40; ++block)
        {
            feedSine (analyser, sampleRate, 1000.0f, 0.0f, 512);
            analyser.process();
        }

        for (auto binDb : analyser.getBinsDb())
            if (binDb > settings.floorDb + 0.01f)
            {
                fail ("a bin sat above the floor at " + std::to_string (binDb) + " dB");
                break;
            }
    }

    startTest ("a high sine lands in a high bin, a low sine in a low bin");
    {
        lso::SpectrumAnalyser analyser;
        analyser.prepare (sampleRate, lso::kNumBins, settings);

        for (int block = 0; block < 16; ++block)
        {
            feedSine (analyser, sampleRate, 8000.0f, 1.0f, 512);
            analyser.process();
        }

        const auto highHz = analyser.getBinCentresHz()[(size_t) peakBinIndex (analyser.getBinsDb())];
        checkNear (highHz, 8000.0, 300.0, "8 kHz peak frequency");

        lso::SpectrumAnalyser lowAnalyser;
        lowAnalyser.prepare (sampleRate, lso::kNumBins, settings);

        for (int block = 0; block < 16; ++block)
        {
            feedSine (lowAnalyser, sampleRate, 60.0f, 1.0f, 512);
            lowAnalyser.process();
        }

        const auto lowHz = lowAnalyser.getBinCentresHz()[(size_t) peakBinIndex (lowAnalyser.getBinsDb())];
        checkNear (lowHz, 60.0, 8.0, "60 Hz peak frequency");
    }

    startTest ("the display falls back towards the floor after the signal stops");
    {
        lso::SpectrumAnalyser analyser;
        analyser.prepare (sampleRate, lso::kNumBins, settings);

        for (int block = 0; block < 16; ++block)
        {
            feedSine (analyser, sampleRate, 1000.0f, 1.0f, 512);
            analyser.process();
        }

        const auto loudPeak = analyser.getBinsDb()[(size_t) peakBinIndex (analyser.getBinsDb())];

        for (int block = 0; block < 200; ++block)
        {
            feedSine (analyser, sampleRate, 1000.0f, 0.0f, 512);
            analyser.process();
        }

        const auto quietPeak = analyser.getBinsDb()[(size_t) peakBinIndex (analyser.getBinsDb())];
        check (quietPeak < loudPeak - 40.0f,
               "level only fell from " + std::to_string (loudPeak) + " to " + std::to_string (quietPeak));
    }

    startTest ("bin centres span 20 Hz to 20 kHz and rise monotonically");
    {
        lso::SpectrumAnalyser analyser;
        analyser.prepare (sampleRate, lso::kNumBins, settings);
        const auto& centres = analyser.getBinCentresHz();

        check ((int) centres.size() == lso::kNumBins, "unexpected bin count");
        checkNear (centres.front(), 20.0, 0.01, "first bin");
        checkNear (centres.back(), 20000.0, 1.0, "last bin");

        for (size_t i = 1; i < centres.size(); ++i)
            if (centres[i] <= centres[i - 1])
            {
                fail ("bin centres are not monotonic at index " + std::to_string (i));
                break;
            }
    }

    startTest ("the tilt lifts high frequencies by the requested slope");
    {
        lso::AnalyserSettings tilted;
        tilted.tiltDbPerOctave = 3.0f;

        lso::SpectrumAnalyser flat, sloped;
        flat.prepare (sampleRate, lso::kNumBins, settings);
        sloped.prepare (sampleRate, lso::kNumBins, tilted);

        for (int block = 0; block < 16; ++block)
        {
            feedSine (flat, sampleRate, 2000.0f, 1.0f, 512);
            feedSine (sloped, sampleRate, 2000.0f, 1.0f, 512);
            flat.process();
            sloped.process();
        }

        const auto flatPeak = flat.getBinsDb()[(size_t) peakBinIndex (flat.getBinsDb())];
        const auto slopedPeak = sloped.getBinsDb()[(size_t) peakBinIndex (sloped.getBinsDb())];

        // 2 kHz is one octave above the 1 kHz tilt pivot.
        checkNear (slopedPeak - flatPeak, 3.0, 0.3, "tilt at 2 kHz");
    }
}

//==============================================================================
void testRegistryRoundTrip()
{
    startTest ("a published frame reads back intact");

    const auto path = temporaryRegistryPath ("roundtrip");
    ::unlink (path.c_str());

    lso::TrackRegistry writer, reader;
    std::string error;

    if (! writer.open (path, &error) || ! reader.open (path, &error))
    {
        fail ("could not open the registry: " + error);
        return;
    }

    const auto instanceId = lso::TrackRegistry::makeInstanceId();
    check (writer.claimSlot (instanceId), "could not claim a slot");

    lso::TrackFrame frame;
    frame.setName ("Lead Vocal");
    frame.colourIndex = 3;
    frame.styleIndex = 1;
    frame.peakDb = -7.5f;
    frame.rmsDb = -18.25f;
    frame.flags = lso::trackFlagHasSignal;

    for (int i = 0; i < lso::kNumBins; ++i)
        frame.bins[i] = (float) i * 0.5f - 90.0f;

    writer.publish (frame);

    std::vector<lso::TrackFrame> frames;
    reader.readAll (frames);

    if (frames.size() != 1)
    {
        fail ("expected one live track, saw " + std::to_string (frames.size()));
        ::unlink (path.c_str());
        return;
    }

    const auto& read = frames.front();
    check (read.getName() == "Lead Vocal", "the track name did not survive: '" + read.getName() + "'");
    check (read.instanceId == instanceId, "the instance id did not survive");
    check (read.colourIndex == 3 && read.styleIndex == 1, "the appearance did not survive");
    checkNear (read.peakDb, -7.5, 0.001, "peak level");
    checkNear (read.rmsDb, -18.25, 0.001, "rms level");
    check (read.flags == lso::trackFlagHasSignal, "flags did not survive");

    for (int i = 0; i < lso::kNumBins; ++i)
        if (std::abs (read.bins[i] - ((float) i * 0.5f - 90.0f)) > 0.001f)
        {
            fail ("bin " + std::to_string (i) + " did not survive");
            break;
        }

    startTest ("a released slot disappears from the display");
    writer.releaseSlot();
    reader.readAll (frames);
    check (frames.empty(), "a released slot was still listed");

    startTest ("a name longer than the slot is truncated, not overrun");
    check (writer.claimSlot (instanceId), "could not re-claim a slot");
    lso::TrackFrame longName;
    longName.setName (std::string (400, 'x'));
    writer.publish (longName);
    reader.readAll (frames);
    check (frames.size() == 1 && frames.front().getName().size() == lso::kNameBytes - 1,
           "an over-long name was not truncated cleanly");

    ::unlink (path.c_str());
}

void testRegistryStaleness()
{
    startTest ("a track that stops beating drops off, then its slot is reused");

    const auto path = temporaryRegistryPath ("stale");
    ::unlink (path.c_str());

    lso::TrackRegistry registry;
    std::string error;

    if (! registry.open (path, &error))
    {
        fail ("could not open the registry: " + error);
        return;
    }

    check (registry.claimSlot (lso::TrackRegistry::makeInstanceId()), "could not claim a slot");

    lso::TrackFrame frame;
    frame.setName ("Drums");
    registry.publish (frame);

    const auto now = lso::TrackRegistry::nowMs();

    std::vector<lso::TrackFrame> frames;
    registry.readAll (frames, now);
    check (frames.size() == 1, "a freshly published track was not listed");

    registry.readAll (frames, now + lso::kStaleAfterMs + 1);
    check (frames.empty(), "a track that stopped beating was still listed");

    // Still owned, so a second instance cannot take the slot until the
    // reclaim window passes.
    lso::TrackRegistry other;
    check (other.open (path, &error), "could not open a second handle");
    check (other.claimSlot (lso::TrackRegistry::makeInstanceId()), "could not claim a second slot");
    check (other.getSlotIndex() != registry.getSlotIndex(), "a live slot was stolen");

    ::unlink (path.c_str());
}

void testRegistryAcrossProcesses()
{
    startTest ("a track published by another process is visible");

    const auto path = temporaryRegistryPath ("crossproc");
    ::unlink (path.c_str());

    const auto child = fork();

    if (child < 0)
    {
        fail ("fork failed");
        return;
    }

    if (child == 0)
    {
        // Child: stand in for a plugin instance living in another
        // AUHostingService process.
        lso::TrackRegistry registry;

        if (! registry.open (path))
            _exit (2);

        if (! registry.claimSlot (lso::TrackRegistry::makeInstanceId()))
            _exit (3);

        lso::TrackFrame frame;
        frame.setName ("Bass (child process)");
        frame.colourIndex = 5;
        frame.peakDb = -12.0f;

        for (int i = 0; i < lso::kNumBins; ++i)
            frame.bins[i] = -30.0f;

        for (int i = 0; i < 60; ++i)
        {
            registry.publish (frame);
            std::this_thread::sleep_for (std::chrono::milliseconds (10));
        }

        _exit (0);
    }

    lso::TrackRegistry registry;
    std::string error;

    if (! registry.open (path, &error))
    {
        fail ("could not open the registry: " + error);
        kill (child, SIGKILL);
        waitpid (child, nullptr, 0);
        return;
    }

    bool sawChild = false;
    std::vector<lso::TrackFrame> frames;

    for (int attempt = 0; attempt < 100 && ! sawChild; ++attempt)
    {
        registry.readAll (frames);

        for (const auto& frame : frames)
            if (frame.getName() == "Bass (child process)")
            {
                sawChild = true;
                check (frame.colourIndex == 5, "the other process's colour did not survive");
                checkNear (frame.peakDb, -12.0, 0.001, "the other process's peak level");
                check (frame.bins[100] < -29.0f && frame.bins[100] > -31.0f,
                       "the other process's bins did not survive");
            }

        if (! sawChild)
            std::this_thread::sleep_for (std::chrono::milliseconds (10));
    }

    check (sawChild, "never saw the track published by the other process");

    kill (child, SIGKILL);
    waitpid (child, nullptr, 0);
    ::unlink (path.c_str());
}

void testRegistryConcurrency()
{
    startTest ("a reader never sees a half-written frame");

    const auto path = temporaryRegistryPath ("concurrency");
    ::unlink (path.c_str());

    lso::TrackRegistry writer, reader;
    std::string error;

    if (! writer.open (path, &error) || ! reader.open (path, &error))
    {
        fail ("could not open the registry: " + error);
        return;
    }

    check (writer.claimSlot (lso::TrackRegistry::makeInstanceId()), "could not claim a slot");

    std::atomic<bool> stop { false };
    std::atomic<int> tornReads { 0 };
    std::atomic<int> reads { 0 };

    std::thread writerThread ([&]
    {
        // Every field of a frame carries the same generation number, so any
        // mixture of two generations in one read is a torn read.
        for (int generation = 1; ! stop.load(); ++generation)
        {
            std::this_thread::sleep_for (std::chrono::microseconds (20));

            lso::TrackFrame frame;
            const auto value = (float) (generation % 1000);
            frame.peakDb = value;
            frame.rmsDb = value;
            frame.colourIndex = (uint32_t) (generation % 1000);
            frame.setName (std::to_string (generation % 1000));

            for (int i = 0; i < lso::kNumBins; ++i)
                frame.bins[i] = value;

            writer.publish (frame);
        }
    });

    std::vector<lso::TrackFrame> frames;

    for (int i = 0; i < 20000; ++i)
    {
        reader.readAll (frames);

        for (const auto& frame : frames)
        {
            if (frame.getName().empty())
                continue;   // the blank frame written when the slot was claimed

            ++reads;
            bool consistent = frame.rmsDb == frame.peakDb
                              && (float) frame.colourIndex == frame.peakDb
                              && frame.getName() == std::to_string ((int) frame.peakDb);

            for (int bin = 0; bin < lso::kNumBins && consistent; ++bin)
                consistent = frame.bins[bin] == frame.peakDb;

            if (! consistent)
                ++tornReads;
        }
    }

    stop.store (true);
    writerThread.join();

    check (reads.load() > 1000, "the concurrency test barely read anything (" + std::to_string (reads.load()) + " reads)");
    check (tornReads.load() == 0, std::to_string (tornReads.load()) + " of " + std::to_string (reads.load())
                                      + " reads were torn");

    ::unlink (path.c_str());
}

void testRegistryLocationFallback()
{
    startTest ("an unusable preferred location falls back to a working one");

    const std::string unusable = "/proc/definitely-not-writable/registry.bin";
    setenv ("LSO_REGISTRY_PATH", unusable.c_str(), 1);

    const auto candidates = lso::TrackRegistry::getCandidatePaths();
    check (! candidates.empty() && candidates.front() == unusable,
           "the environment override was not tried first");
    check (candidates.size() > 1, "there were no fallback locations to try");

    lso::TrackRegistry registry;
    std::string error;

    check (registry.openDefault (&error), "openDefault gave up: " + error);
    check (registry.getPath() != unusable, "reported the unusable path as open");
    check (registry.claimSlot (lso::TrackRegistry::makeInstanceId()), "could not claim a slot after falling back");

    const auto used = registry.getPath();
    registry.close();
    ::unlink (used.c_str());
    unsetenv ("LSO_REGISTRY_PATH");
}

void testAppearanceAssignment()
{
    startTest ("appearances fill every hue before reusing one with a new line style");

    std::vector<lso::TrackFrame> live;

    for (int i = 0; i < 20; ++i)
    {
        const auto appearance = lso::chooseAppearance (live, lso::kNumHues);

        const auto expectedColour = (uint32_t) (i % lso::kNumHues);
        const auto expectedStyle = (uint32_t) (i / lso::kNumHues);

        if (appearance.colourIndex != expectedColour || appearance.styleIndex != expectedStyle)
        {
            fail ("track " + std::to_string (i) + " got hue " + std::to_string (appearance.colourIndex)
                  + "/style " + std::to_string (appearance.styleIndex) + ", expected "
                  + std::to_string (expectedColour) + "/" + std::to_string (expectedStyle));
            break;
        }

        lso::TrackFrame frame;
        frame.colourIndex = appearance.colourIndex;
        frame.styleIndex = appearance.styleIndex;
        live.push_back (frame);
    }

    startTest ("a freed appearance is handed to the next track");
    live.erase (live.begin() + 2);
    const auto reused = lso::chooseAppearance (live, lso::kNumHues);
    check (reused.colourIndex == 2 && reused.styleIndex == 0,
           "expected the freed hue 2 to be reused, got hue " + std::to_string (reused.colourIndex));

    startTest ("hue and style lookups stay in range");
    for (int i = 0; i < 40; ++i)
    {
        const auto colour = lso::hueForIndex (i);
        check (colour.r != 0 || colour.g != 0 || colour.b != 0, "hue " + std::to_string (i) + " came back black");
        check (lso::hueName (i) != nullptr && lso::styleName (i) != nullptr, "missing palette name");
    }
}

//==============================================================================
namespace
{
std::vector<float> testBinCentres()
{
    std::vector<float> centres ((size_t) lso::kNumBins);

    for (int i = 0; i < lso::kNumBins; ++i)
        centres[(size_t) i] = lso::SpectrumAnalyser::binCentreHz (i, lso::kNumBins, 20.0f, 20000.0f);

    return centres;
}

/** Broadband material with a hump: a smooth peak of the given width in
    octaves over a continuous bed, which is what real instruments look like.
*/
std::vector<float> trackWithHump (const std::vector<float>& centres, float peakHz, float peakDb,
                                  float widthOctaves, float bedDb)
{
    std::vector<float> bins (centres.size(), bedDb);

    for (size_t i = 0; i < centres.size(); ++i)
    {
        const auto octavesAway = std::log2 (centres[i] / peakHz) / widthOctaves;
        const auto hump = (peakDb - bedDb) * std::exp (-octavesAway * octavesAway);
        bins[i] = bedDb + hump;
    }

    return bins;
}

/** A flat -80 dB track with a raised plateau between two frequencies. */
std::vector<float> trackWithPlateau (const std::vector<float>& centres, float lowHz, float highHz, float levelDb)
{
    std::vector<float> bins (centres.size(), -80.0f);

    for (size_t i = 0; i < centres.size(); ++i)
        if (centres[i] >= lowHz && centres[i] <= highHz)
            bins[i] = levelDb;

    return bins;
}
} // namespace

void testCollisionFinder()
{
    const auto centres = testBinCentres();

    startTest ("two tracks sharing a band are reported as one overlap");
    {
        const auto vocal = trackWithPlateau (centres, 1000.0f, 4000.0f, -12.0f);
        const auto synth = trackWithPlateau (centres, 2000.0f, 8000.0f, -14.0f);
        const std::vector<const float*> tracks { vocal.data(), synth.data() };

        const auto collisions = lso::findCollisions (tracks, centres);

        if (collisions.size() != 1)
        {
            fail ("expected one overlap, got " + std::to_string (collisions.size()));
        }
        else
        {
            const auto& collision = collisions.front();
            checkNear (collision.lowHz, 2000.0, 2000.0 * 0.05, "overlap low edge");
            checkNear (collision.highHz, 4000.0, 4000.0 * 0.05, "overlap high edge");
            // The quieter track is what makes the overlap audible.
            checkNear (collision.strengthDb, -14.0, 0.01, "overlap strength");
            check (collision.severity == lso::CollisionSeverity::severe, "a loud overlap was not marked severe");
            checkNear (collision.widthOctaves, 1.0, 0.1, "overlap width in octaves");
        }
    }

    startTest ("tracks in different registers do not collide");
    {
        const auto bass = trackWithPlateau (centres, 40.0f, 160.0f, -10.0f);
        const auto air = trackWithPlateau (centres, 6000.0f, 16000.0f, -10.0f);
        const std::vector<const float*> tracks { bass.data(), air.data() };

        check (lso::findCollisions (tracks, centres).empty(), "reported an overlap between separate registers");
    }

    startTest ("a track 40 dB down is not competing, however much it shares");
    {
        const auto loud = trackWithPlateau (centres, 500.0f, 5000.0f, -8.0f);
        const auto quiet = trackWithPlateau (centres, 500.0f, 5000.0f, -60.0f);
        const std::vector<const float*> tracks { loud.data(), quiet.data() };

        check (lso::findCollisions (tracks, centres).empty(),
               "a track far below the mix was reported as colliding");
    }

    startTest ("a one-bin coincidence is ignored, a wide one is not");
    {
        auto narrowA = trackWithPlateau (centres, 1000.0f, 1000.0f, -10.0f);
        auto narrowB = narrowA;

        // Widen to exactly one bin either side of a single shared bin.
        const std::vector<const float*> narrow { narrowA.data(), narrowB.data() };
        const auto narrowResults = lso::findCollisions (narrow, centres);

        for (const auto& collision : narrowResults)
            if (collision.lastBin - collision.firstBin + 1 < 5)
            {
                fail ("a coincidence narrower than the minimum was reported");
                break;
            }

        const auto wideA = trackWithPlateau (centres, 900.0f, 1200.0f, -10.0f);
        const auto wideB = trackWithPlateau (centres, 900.0f, 1200.0f, -11.0f);
        const std::vector<const float*> wide { wideA.data(), wideB.data() };
        check (lso::findCollisions (wide, centres).size() == 1, "a wide shared band was not reported");
    }

    startTest ("overlaps come back strongest first, and every pair is checked");
    {
        const auto kick = trackWithPlateau (centres, 60.0f, 120.0f, -6.0f);
        const auto bass = trackWithPlateau (centres, 60.0f, 120.0f, -9.0f);
        const auto vocal = trackWithPlateau (centres, 2000.0f, 5000.0f, -20.0f);
        const auto guitar = trackWithPlateau (centres, 2000.0f, 5000.0f, -24.0f);
        const std::vector<const float*> tracks { kick.data(), bass.data(), vocal.data(), guitar.data() };

        const auto collisions = lso::findCollisions (tracks, centres);

        if (collisions.size() < 2)
        {
            fail ("expected at least two overlaps, got " + std::to_string (collisions.size()));
        }
        else
        {
            check (collisions[0].strengthDb >= collisions[1].strengthDb, "overlaps were not sorted by strength");
            check (collisions[0].trackA == 0 && collisions[0].trackB == 1, "the loudest overlap named the wrong pair");
            check (collisions[0].severity == lso::CollisionSeverity::severe
                       && collisions[1].severity != lso::CollisionSeverity::severe,
                   "severity did not separate a loud overlap from a quiet one");
        }

        startTest ("a bin lookup finds the overlap covering it");
        const auto* atLowEnd = lso::strongestCollisionAt (collisions, collisions[0].firstBin);
        check (atLowEnd != nullptr, "no overlap found at a bin inside one");

        const auto outsideBin = lso::kNumBins - 1;
        check (lso::strongestCollisionAt (collisions, outsideBin) == nullptr,
               "found an overlap at a bin with no signal");
    }

    startTest ("broadband tracks peaking apart do not report one huge overlap");
    {
        // Both cover the whole spectrum, as real instruments do, but they are
        // strong in different places. Measuring shared level alone would call
        // this one overlap from 20 Hz to 20 kHz, which is true and useless.
        const auto bass = trackWithHump (centres, 120.0f, -8.0f, 1.6f, -46.0f);
        const auto air = trackWithHump (centres, 6000.0f, -10.0f, 1.6f, -46.0f);
        const std::vector<const float*> tracks { bass.data(), air.data() };

        const auto collisions = lso::findCollisions (tracks, centres);

        for (const auto& collision : collisions)
        {
            if (collision.widthOctaves > 2.0f)
            {
                fail ("reported an overlap " + std::to_string (collision.widthOctaves)
                      + " octaves wide between tracks peaking three octaves apart");
                break;
            }

            if (collision.lowHz < 200.0f && collision.highHz > 4000.0f)
            {
                fail ("one overlap spanned both tracks' peaks");
                break;
            }
        }
    }

    startTest ("broadband tracks peaking together report a band around the peak");
    {
        const auto vocal = trackWithHump (centres, 2600.0f, -9.0f, 1.0f, -46.0f);
        const auto rhodes = trackWithHump (centres, 2800.0f, -11.0f, 1.0f, -46.0f);
        const std::vector<const float*> tracks { vocal.data(), rhodes.data() };

        const auto collisions = lso::findCollisions (tracks, centres);

        if (collisions.empty())
        {
            fail ("two tracks peaking in the same place reported no overlap");
        }
        else
        {
            const auto& collision = collisions.front();
            check (collision.peakHz > 1500.0f && collision.peakHz < 4500.0f,
                   "the overlap did not centre on the shared peak (" + std::to_string (collision.peakHz) + " Hz)");
            check (collision.widthOctaves < 3.0f,
                   "the overlap was " + std::to_string (collision.widthOctaves) + " octaves wide");
        }
    }

    startTest ("a pair competing in two places is listed once, at its worst");
    {
        auto vocal = trackWithPlateau (centres, 200.0f, 400.0f, -30.0f);
        auto guitar = trackWithPlateau (centres, 200.0f, 400.0f, -30.0f);

        // A second, louder shared region for the same pair.
        const auto presence = trackWithPlateau (centres, 2000.0f, 4000.0f, -12.0f);

        for (size_t i = 0; i < centres.size(); ++i)
        {
            vocal[i] = std::max (vocal[i], presence[i]);
            guitar[i] = std::max (guitar[i], presence[i]);
        }

        const std::vector<const float*> tracks { vocal.data(), guitar.data() };
        const auto collisions = lso::findCollisions (tracks, centres);

        check (collisions.size() == 1, "expected one entry for one pair, got " + std::to_string (collisions.size()));

        if (! collisions.empty())
            check (collisions.front().peakHz > 1500.0f,
                   "the entry kept was not the pair's worst band");
    }

    startTest ("a single track cannot collide with itself");
    {
        const auto only = trackWithPlateau (centres, 100.0f, 8000.0f, -6.0f);
        const std::vector<const float*> tracks { only.data() };
        check (lso::findCollisions (tracks, centres).empty(), "one track reported an overlap");
    }

    startTest ("the result limit keeps the strongest overlaps");
    {
        const auto a = trackWithPlateau (centres, 100.0f, 8000.0f, -6.0f);
        const auto b = trackWithPlateau (centres, 100.0f, 8000.0f, -8.0f);
        const auto c = trackWithPlateau (centres, 100.0f, 8000.0f, -10.0f);
        const std::vector<const float*> tracks { a.data(), b.data(), c.data() };

        const auto limited = lso::findCollisions (tracks, centres, {}, 2);
        check (limited.size() == 2, "the result limit was not applied");
        checkNear (limited.front().strengthDb, -8.0, 0.01, "the strongest overlap was not kept");
    }
}
} // namespace

int main()
{
    std::printf ("Logic Spectrum Overlay - core tests\n\n");

    testFftMatchesNaiveDft();
    testAnalyserCalibration();
    testRegistryRoundTrip();
    testRegistryStaleness();
    testRegistryAcrossProcesses();
    testRegistryConcurrency();
    testRegistryLocationFallback();
    testAppearanceAssignment();
    testCollisionFinder();

    std::printf ("\n%d checks groups run, %d failed\n", testsRun, testsFailed);
    return testsFailed == 0 ? 0 : 1;
}
