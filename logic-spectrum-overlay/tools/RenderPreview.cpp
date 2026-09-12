// Renders the plugin's real editor, driven by several plugin instances
// publishing at once, to PNG. Instances in one process are exactly what Logic
// produces when the plugin is on several tracks, so this exercises the whole
// path: audio in, analysis, shared registry, overlay drawing.

#include <juce_audio_utils/juce_audio_utils.h>

#include <cmath>
#include <thread>

#include "../src/plugin/PluginEditor.h"
#include "../src/plugin/PluginProcessor.h"

namespace
{
constexpr double sampleRate = 48000.0;
constexpr int blockSize = 512;

struct Partial
{
    float frequencyHz, amplitude;
};

/** A track's worth of test material: a few partials over a tilted noise bed. */
struct TestSource
{
    juce::String name;
    std::vector<Partial> partials;
    float noiseLevel = 0.0f;
    float noiseTiltPerBin = 0.0f;   // >0 brightens, <0 darkens
    std::vector<double> phases;
    juce::Random random;
    float noiseState = 0.0f;

    void fill (juce::AudioBuffer<float>& buffer)
    {
        phases.resize (partials.size(), 0.0);
        buffer.clear();

        for (int n = 0; n < buffer.getNumSamples(); ++n)
        {
            float sample = 0.0f;

            for (size_t p = 0; p < partials.size(); ++p)
            {
                sample += partials[p].amplitude * (float) std::sin (phases[p]);
                phases[p] += 2.0 * juce::MathConstants<double>::pi * (double) partials[p].frequencyHz / sampleRate;

                if (phases[p] > 2.0 * juce::MathConstants<double>::pi)
                    phases[p] -= 2.0 * juce::MathConstants<double>::pi;
            }

            if (noiseLevel > 0.0f)
            {
                const auto white = random.nextFloat() * 2.0f - 1.0f;

                // One-pole shaping, so each track's noise bed has its own slope.
                noiseState += (white - noiseState) * (noiseTiltPerBin > 0.0f ? 0.85f : 0.06f);
                sample += noiseLevel * (noiseTiltPerBin > 0.0f ? white - noiseState : noiseState);
            }

            for (int channel = 0; channel < buffer.getNumChannels(); ++channel)
                buffer.setSample (channel, n, sample);
        }
    }
};

lso::SpectrumView* findSpectrumView (juce::Component& parent)
{
    for (auto* child : parent.getChildren())
    {
        if (auto* view = dynamic_cast<lso::SpectrumView*> (child))
            return view;

        if (auto* found = findSpectrumView (*child))
            return found;
    }

    return nullptr;
}

void writePng (juce::Component& component, const juce::File& file)
{
    const auto image = component.createComponentSnapshot (component.getLocalBounds(), true, 1.0f);
    file.deleteFile();

    juce::FileOutputStream stream (file);
    juce::PNGImageFormat png;

    if (stream.openedOk() && png.writeImageToStream (image, stream))
        std::printf ("wrote %s (%d x %d)\n", file.getFullPathName().toRawUTF8(),
                     image.getWidth(), image.getHeight());
    else
        std::printf ("FAILED to write %s\n", file.getFullPathName().toRawUTF8());
}
} // namespace

int main (int argc, char** argv)
{
    const juce::ScopedJuceInitialiser_GUI juceInitialiser;

    const juce::File outputDirectory (argc > 1 ? juce::String (argv[1])
                                               : juce::File::getCurrentWorkingDirectory().getFullPathName());
    outputDirectory.createDirectory();

    std::vector<TestSource> sources {
        { "Kick",       { { 52.0f, 0.62f }, { 104.0f, 0.16f }, { 156.0f, 0.05f } }, 0.02f, -1.0f, {}, {}, 0.0f },
        { "Bass",       { { 82.0f, 0.42f }, { 164.0f, 0.22f }, { 246.0f, 0.12f }, { 328.0f, 0.05f } }, 0.01f, -1.0f, {}, {}, 0.0f },
        { "Lead Vocal", { { 294.0f, 0.30f }, { 588.0f, 0.20f }, { 1176.0f, 0.12f }, { 2352.0f, 0.07f }, { 4704.0f, 0.03f } }, 0.015f, 1.0f, {}, {}, 0.0f },
        { "Rhodes",     { { 220.0f, 0.24f }, { 440.0f, 0.18f }, { 880.0f, 0.10f }, { 1760.0f, 0.05f } }, 0.008f, 1.0f, {}, {}, 0.0f },
        { "Hi-Hats",    { { 6300.0f, 0.10f }, { 9400.0f, 0.07f } }, 0.10f, 1.0f, {}, {}, 0.0f }
    };

    std::vector<std::unique_ptr<lso::SpectrumOverlayProcessor>> processors;

    for (auto& source : sources)
    {
        auto processor = std::make_unique<lso::SpectrumOverlayProcessor>();
        processor->setPlayConfigDetails (2, 2, sampleRate, blockSize);
        processor->prepareToPlay (sampleRate, blockSize);
        processor->setTrackNameOverride (source.name);

        if (! processor->isRegistryOpen())
            std::printf ("WARNING: %s could not join the registry: %s\n",
                         source.name.toRawUTF8(), processor->getRegistryStatus().toRawUTF8());

        processors.push_back (std::move (processor));
    }

    // Push audio through every instance for long enough that the analysis
    // threads have published a settled picture.
    juce::AudioBuffer<float> buffer (2, blockSize);
    juce::MidiBuffer midi;

    for (int block = 0; block < 160; ++block)
    {
        for (size_t i = 0; i < sources.size(); ++i)
        {
            sources[i].fill (buffer);
            processors[i]->processBlock (buffer, midi);
        }

        std::this_thread::sleep_for (std::chrono::milliseconds (8));
    }

    auto& host = *processors.front();
    std::unique_ptr<juce::AudioProcessorEditor> editor (host.createEditor());
    editor->setSize (1120, 640);

    auto pump = [] (int milliseconds)
    {
        juce::MessageManager::getInstance()->runDispatchLoopUntil (milliseconds);
    };

    pump (400);
    writePng (*editor, outputDirectory.getChildFile ("overlay-all-tracks.png"));

    // The crosshair readout, which is where exact numbers are read off.
    if (auto* view = findSpectrumView (*editor))
    {
        const auto position = juce::Point<float> ((float) view->getWidth() * 0.42f,
                                                  (float) view->getHeight() * 0.42f);

        const juce::MouseEvent event (juce::Desktop::getInstance().getMainMouseSource(),
                                      position, juce::ModifierKeys::currentModifiers,
                                      1.0f, 0.0f, 0.0f, 0.0f, 0.0f,
                                      view, view, juce::Time::getCurrentTime(),
                                      position, juce::Time::getCurrentTime(), 0, false);

        view->mouseMove (event);
        pump (120);
        writePng (*editor, outputDirectory.getChildFile ("overlay-readout.png"));
        view->mouseExit (event);
    }
    else
    {
        std::printf ("FAILED to find the spectrum view\n");
    }

    // Two tracks hidden: the show/hide half of the job.
    host.setTrackHidden ("Rhodes", true);
    host.setTrackHidden ("Hi-Hats", true);
    pump (300);
    writePng (*editor, outputDirectory.getChildFile ("overlay-two-hidden.png"));

    editor.reset();
    processors.clear();
    return 0;
}
