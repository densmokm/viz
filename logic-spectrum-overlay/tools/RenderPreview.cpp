// Renders the plugin's real editor, driven by several plugin instances
// publishing at once, to PNG. Instances in one process are exactly what Logic
// produces when the plugin is on several tracks, so this exercises the whole
// path: audio in, analysis, shared registry, overlay drawing.

#include <juce_audio_utils/juce_audio_utils.h>

#include <cmath>
#include <thread>

#include "../src/plugin/CollisionListView.h"
#include "../src/plugin/PluginEditor.h"
#include "../src/plugin/PluginProcessor.h"

namespace
{
constexpr double sampleRate = 48000.0;
constexpr int blockSize = 512;

/** A two-pole bandpass, so test material can be built from resonances rather
    than pure tones and looks like something a microphone produced.
*/
struct Resonator
{
    float g = 0.0f, k = 1.0f, a1 = 0.0f, a2 = 0.0f, a3 = 0.0f;
    float ic1 = 0.0f, ic2 = 0.0f;

    void set (float frequencyHz, float q)
    {
        g = (float) std::tan (juce::MathConstants<double>::pi * (double) frequencyHz / sampleRate);
        k = 1.0f / q;
        a1 = 1.0f / (1.0f + g * (g + k));
        a2 = g * a1;
        a3 = g * a2;
    }

    float process (float input)
    {
        const auto v3 = input - ic2;
        const auto v1 = a1 * ic1 + a2 * v3;
        const auto v2 = ic2 + a2 * ic1 + a3 * v3;
        ic1 = 2.0f * v1 - ic1;
        ic2 = 2.0f * v2 - ic2;
        return v1;
    }
};

struct Band
{
    float frequencyHz, q, gain;
};

struct TestSource
{
    TestSource (juce::String nameToUse, std::vector<Band> bandsToUse)
        : name (std::move (nameToUse)), bands (std::move (bandsToUse)) {}

    juce::String name;
    std::vector<Band> bands;

    std::vector<Resonator> resonators;
    juce::Random random;
    bool prepared = false;

    void fill (juce::AudioBuffer<float>& buffer)
    {
        if (! prepared)
        {
            resonators.resize (bands.size());

            for (size_t i = 0; i < bands.size(); ++i)
                resonators[i].set (bands[i].frequencyHz, bands[i].q);

            prepared = true;
        }

        buffer.clear();

        for (int n = 0; n < buffer.getNumSamples(); ++n)
        {
            const auto noise = random.nextFloat() * 2.0f - 1.0f;
            float sample = 0.0f;

            for (size_t i = 0; i < bands.size(); ++i)
                sample += bands[i].gain * resonators[i].process (noise);

            for (int channel = 0; channel < buffer.getNumChannels(); ++channel)
                buffer.setSample (channel, n, sample);
        }
    }
};

template <typename ComponentType>
ComponentType* findChildOfClass (juce::Component& parent)
{
    for (auto* child : parent.getChildren())
    {
        if (auto* found = dynamic_cast<ComponentType*> (child))
            return found;

        if (auto* found = findChildOfClass<ComponentType> (*child))
            return found;
    }

    return nullptr;
}

juce::TextButton* findButton (juce::Component& parent, const juce::String& text)
{
    for (auto* child : parent.getChildren())
    {
        if (auto* button = dynamic_cast<juce::TextButton*> (child))
            if (button->getButtonText().startsWith (text))
                return button;

        if (auto* found = findButton (*child, text))
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

    // Deliberately arranged so two pairs compete: kick against bass in the low
    // end, and vocal against the Rhodes through the presence region.
    std::vector<TestSource> sources {
        { "Kick",       { { 55.0f, 1.4f, 1.00f }, { 110.0f, 2.0f, 0.45f }, { 2600.0f, 1.0f, 0.05f } } },
        { "Bass",       { { 85.0f, 1.8f, 0.85f }, { 170.0f, 2.2f, 0.55f }, { 430.0f, 2.5f, 0.20f } } },
        { "Lead Vocal", { { 240.0f, 2.5f, 0.55f }, { 750.0f, 2.0f, 0.42f }, { 2600.0f, 1.6f, 0.34f }, { 4200.0f, 2.0f, 0.16f } } },
        { "Rhodes",     { { 420.0f, 2.2f, 0.40f }, { 980.0f, 2.4f, 0.30f }, { 2700.0f, 1.5f, 0.30f }, { 3900.0f, 2.2f, 0.18f } } },
        { "Hi-Hats",    { { 7200.0f, 0.9f, 0.30f }, { 11500.0f, 1.1f, 0.22f } } }
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
    if (auto* view = findChildOfClass<lso::SpectrumView> (*editor))
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

    // The overlaps panel, with the worst one picked out on the plot.
    if (auto* tab = findButton (*editor, "Overlaps"))
    {
        tab->triggerClick();
        pump (300);

        if (auto* list = findChildOfClass<lso::CollisionListView> (*editor))
        {
            list->setHoveredRow (0);
            pump (120);
        }

        writePng (*editor, outputDirectory.getChildFile ("overlay-overlaps.png"));

        // The list is a triage tool, so it has to hold still while you read
        // it. Sample what it says over a couple of seconds.
        std::printf ("overlap list over time: %s", tab->getButtonText().toRawUTF8());

        for (int i = 0; i < 4; ++i)
        {
            pump (500);
            std::printf (" -> %s", tab->getButtonText().toRawUTF8());
        }

        std::printf ("\n");

        if (auto* tracksTab = findButton (*editor, "Tracks"))
        {
            tracksTab->triggerClick();
            pump (200);
        }
    }
    else
    {
        std::printf ("FAILED to find the overlaps tab\n");
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
