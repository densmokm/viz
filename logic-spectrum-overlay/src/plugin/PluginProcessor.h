#pragma once

#include <juce_audio_processors/juce_audio_processors.h>

#include <atomic>
#include <vector>

#include "../core/Palette.h"
#include "../core/SpectrumAnalyser.h"
#include "../core/TrackRegistry.h"

namespace lso
{

/** Display options. Owned by the processor so they persist with the session
    and are readable from the audio, analysis and message threads alike.
*/
struct ViewSettings
{
    std::atomic<float> topDb { 6.0f };
    std::atomic<float> bottomDb { -84.0f };
    std::atomic<float> tiltDbPerOctave { 3.0f };
    std::atomic<bool> fillOwnCurve { true };
    std::atomic<bool> soloThisTrack { false };
};

/** One instance per track. Passes audio through untouched, measures the
    spectrum arriving at its slot, and publishes it for every other instance
    to draw.
*/
class SpectrumOverlayProcessor final : public juce::AudioProcessor,
                                       private juce::Thread
{
public:
    SpectrumOverlayProcessor();
    ~SpectrumOverlayProcessor() override;

    //== AudioProcessor ========================================================
    void prepareToPlay (double sampleRate, int samplesPerBlock) override;
    void releaseResources() override;
    bool isBusesLayoutSupported (const BusesLayout& layouts) const override;
    using AudioProcessor::processBlock;
    void processBlock (juce::AudioBuffer<float>&, juce::MidiBuffer&) override;

    juce::AudioProcessorEditor* createEditor() override;
    bool hasEditor() const override { return true; }

    const juce::String getName() const override { return "Spectrum Overlay"; }
    bool acceptsMidi() const override { return false; }
    bool producesMidi() const override { return false; }
    bool isMidiEffect() const override { return false; }
    double getTailLengthSeconds() const override { return 0.0; }

    int getNumPrograms() override { return 1; }
    int getCurrentProgram() override { return 0; }
    void setCurrentProgram (int) override {}
    const juce::String getProgramName (int) override { return "Default"; }
    void changeProgramName (int, const juce::String&) override {}

    void getStateInformation (juce::MemoryBlock& destData) override;
    void setStateInformation (const void* data, int sizeInBytes) override;

    void updateTrackProperties (const TrackProperties& properties) override;

    //== Used by the editor ====================================================
    /** Every track currently publishing, in registry order. */
    void getLiveTracks (std::vector<TrackFrame>& out);

    juce::String getTrackName() const;
    void setTrackNameOverride (const juce::String& name);
    bool hasTrackNameOverride() const;

    uint64_t getInstanceId() const noexcept { return instanceId; }
    bool isRegistryOpen() const noexcept { return registryOpen.load(); }
    juce::String getRegistryStatus() const;

    bool isTrackHidden (const juce::String& trackName) const;
    void setTrackHidden (const juce::String& trackName, bool shouldBeHidden);
    void setHiddenTracks (const juce::StringArray& names);
    juce::StringArray getHiddenTracks() const;

    void setColourOverride (int hueIndex);
    int getColourOverride() const;

    ViewSettings view;

private:
    void run() override;
    void refreshAppearance();
    void publishFrame();

    lso::SpectrumAnalyser analyser;
    lso::TrackRegistry registry;
    lso::AnalyserSettings analyserSettings;

    const uint64_t instanceId { lso::TrackRegistry::makeInstanceId() };
    std::atomic<bool> registryOpen { false };
    juce::String registryError;

    Appearance appearance;
    bool appearanceAssigned = false;
    std::atomic<int> colourOverride { -1 };
    uint64_t lastAppearanceCheckMs = 0;

    mutable juce::CriticalSection stateLock;
    juce::String hostTrackName;
    juce::String trackNameOverride;
    juce::StringArray hiddenTracks;

    std::vector<TrackFrame> scratchFrames;
    std::atomic<float> publishedTilt { 3.0f };

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (SpectrumOverlayProcessor)
};

} // namespace lso
