#include "PluginProcessor.h"
#include "PluginEditor.h"

namespace lso
{

namespace ids
{
const juce::Identifier state { "SpectrumOverlayState" };
const juce::Identifier nameOverride { "nameOverride" };
const juce::Identifier colourOverride { "colourOverride" };
const juce::Identifier hidden { "hiddenTracks" };
const juce::Identifier topDb { "topDb" };
const juce::Identifier bottomDb { "bottomDb" };
const juce::Identifier tilt { "tilt" };
const juce::Identifier fill { "fillOwnCurve" };
const juce::Identifier solo { "soloThisTrack" };
} // namespace ids

SpectrumOverlayProcessor::SpectrumOverlayProcessor()
    : AudioProcessor (BusesProperties()
                          .withInput ("Input", juce::AudioChannelSet::stereo(), true)
                          .withOutput ("Output", juce::AudioChannelSet::stereo(), true)),
      juce::Thread ("Spectrum Overlay publisher")
{
    std::string error;

    if (registry.openDefault (&error) && registry.claimSlot (instanceId))
    {
        registryOpen.store (true);
    }
    else
    {
        registryError = juce::String (error.empty() ? registry.getLastError() : error);

        if (registryError.isEmpty())
            registryError = "could not claim a slot";
    }

    startThread (juce::Thread::Priority::low);
}

SpectrumOverlayProcessor::~SpectrumOverlayProcessor()
{
    stopThread (1500);
    registry.close();
}

//==============================================================================
void SpectrumOverlayProcessor::prepareToPlay (double sampleRate, int)
{
    analyserSettings.tiltDbPerOctave = view.tiltDbPerOctave.load();
    publishedTilt.store (analyserSettings.tiltDbPerOctave);
    analyser.prepare (sampleRate, kNumBins, analyserSettings);
}

void SpectrumOverlayProcessor::releaseResources()
{
    analyser.reset();
}

bool SpectrumOverlayProcessor::isBusesLayoutSupported (const BusesLayout& layouts) const
{
    const auto& output = layouts.getMainOutputChannelSet();

    if (output != juce::AudioChannelSet::mono() && output != juce::AudioChannelSet::stereo())
        return false;

    return output == layouts.getMainInputChannelSet();
}

void SpectrumOverlayProcessor::processBlock (juce::AudioBuffer<float>& buffer, juce::MidiBuffer&)
{
    juce::ScopedNoDenormals noDenormals;

    const auto numInputs = getTotalNumInputChannels();
    const auto numOutputs = getTotalNumOutputChannels();

    for (auto channel = numInputs; channel < numOutputs; ++channel)
        buffer.clear (channel, 0, buffer.getNumSamples());

    // Audio is never touched: this plugin only looks.
    if (numInputs > 0 && buffer.getNumSamples() > 0)
        analyser.pushSamples (buffer.getArrayOfReadPointers(),
                              juce::jmin (numInputs, buffer.getNumChannels()),
                              buffer.getNumSamples());
}

//==============================================================================
void SpectrumOverlayProcessor::run()
{
    while (! threadShouldExit())
    {
        const auto tilt = view.tiltDbPerOctave.load();

        if (! juce::approximatelyEqual (tilt, publishedTilt.load()))
        {
            publishedTilt.store (tilt);
            analyser.setTiltDbPerOctave (tilt);
        }

        if (registryOpen.load())
        {
            refreshAppearance();

            // Publish on every tick, not only when a new frame was analysed:
            // a silent track still has to appear in everyone's track list.
            analyser.process();
            publishFrame();
        }

        wait (30);
    }
}

void SpectrumOverlayProcessor::refreshAppearance()
{
    const auto now = TrackRegistry::nowMs();

    if (appearanceAssigned && now - lastAppearanceCheckMs < 500)
        return;

    lastAppearanceCheckMs = now;
    registry.readAll (scratchFrames, now);

    scratchFrames.erase (std::remove_if (scratchFrames.begin(), scratchFrames.end(),
                                         [this] (const TrackFrame& frame)
                                         {
                                             return frame.instanceId == instanceId;
                                         }),
                         scratchFrames.end());

    const auto clash = registry.appearanceClashesWithOlderTrack (appearance, now);

    if (! appearanceAssigned || clash)
    {
        appearance = chooseAppearance (scratchFrames, kNumHues);
        appearanceAssigned = true;
    }
}

void SpectrumOverlayProcessor::publishFrame()
{
    TrackFrame frame;
    frame.instanceId = instanceId;

    const auto override = colourOverride.load();
    frame.colourIndex = override >= 0 ? (uint32_t) override : appearance.colourIndex;
    frame.styleIndex = appearance.styleIndex;

    frame.setName (getTrackName().toStdString());

    frame.peakDb = analyser.getPeakDb();
    frame.rmsDb = analyser.getRmsDb();
    frame.flags = frame.peakDb > analyserSettings.floorDb + 1.0f ? trackFlagHasSignal : trackFlagNone;

    const auto& bins = analyser.getBinsDb();
    const auto numToCopy = juce::jmin ((int) bins.size(), kNumBins);

    for (int i = 0; i < numToCopy; ++i)
        frame.bins[i] = bins[(size_t) i];

    for (int i = numToCopy; i < kNumBins; ++i)
        frame.bins[i] = analyserSettings.floorDb;

    registry.publish (frame);
}

//==============================================================================
void SpectrumOverlayProcessor::getLiveTracks (std::vector<TrackFrame>& out)
{
    if (! registryOpen.load())
    {
        out.clear();
        return;
    }

    registry.readAll (out);
}

juce::String SpectrumOverlayProcessor::getTrackName() const
{
    const juce::ScopedLock lock (stateLock);

    if (trackNameOverride.isNotEmpty())
        return trackNameOverride;

    if (hostTrackName.isNotEmpty())
        return hostTrackName;

    return "Track " + juce::String ((int) (instanceId % 900) + 100);
}

void SpectrumOverlayProcessor::setTrackNameOverride (const juce::String& name)
{
    const juce::ScopedLock lock (stateLock);
    trackNameOverride = name.trim();
}

bool SpectrumOverlayProcessor::hasTrackNameOverride() const
{
    const juce::ScopedLock lock (stateLock);
    return trackNameOverride.isNotEmpty();
}

void SpectrumOverlayProcessor::updateTrackProperties (const TrackProperties& properties)
{
    const juce::ScopedLock lock (stateLock);

    if (properties.name.has_value())
        hostTrackName = *properties.name;
}

juce::String SpectrumOverlayProcessor::getRegistryStatus() const
{
    if (registryOpen.load())
        return "sharing via " + juce::String (registry.getPath());

    return "not sharing: " + registryError;
}

bool SpectrumOverlayProcessor::isTrackHidden (const juce::String& trackName) const
{
    const juce::ScopedLock lock (stateLock);
    return hiddenTracks.contains (trackName);
}

void SpectrumOverlayProcessor::setTrackHidden (const juce::String& trackName, bool shouldBeHidden)
{
    const juce::ScopedLock lock (stateLock);

    if (shouldBeHidden)
        hiddenTracks.addIfNotAlreadyThere (trackName);
    else
        hiddenTracks.removeString (trackName);
}

void SpectrumOverlayProcessor::setHiddenTracks (const juce::StringArray& names)
{
    const juce::ScopedLock lock (stateLock);
    hiddenTracks = names;
}

juce::StringArray SpectrumOverlayProcessor::getHiddenTracks() const
{
    const juce::ScopedLock lock (stateLock);
    return hiddenTracks;
}

void SpectrumOverlayProcessor::setColourOverride (int hueIndex)
{
    colourOverride.store (hueIndex >= 0 ? hueIndex % kNumHues : -1);
}

int SpectrumOverlayProcessor::getColourOverride() const
{
    return colourOverride.load();
}

//==============================================================================
void SpectrumOverlayProcessor::getStateInformation (juce::MemoryBlock& destData)
{
    juce::ValueTree tree (ids::state);

    {
        const juce::ScopedLock lock (stateLock);
        tree.setProperty (ids::nameOverride, trackNameOverride, nullptr);
        tree.setProperty (ids::hidden, hiddenTracks.joinIntoString ("\n"), nullptr);
    }

    tree.setProperty (ids::colourOverride, colourOverride.load(), nullptr);
    tree.setProperty (ids::topDb, view.topDb.load(), nullptr);
    tree.setProperty (ids::bottomDb, view.bottomDb.load(), nullptr);
    tree.setProperty (ids::tilt, view.tiltDbPerOctave.load(), nullptr);
    tree.setProperty (ids::fill, view.fillOwnCurve.load(), nullptr);
    tree.setProperty (ids::solo, view.soloThisTrack.load(), nullptr);

    if (auto xml = tree.createXml())
        copyXmlToBinary (*xml, destData);
}

void SpectrumOverlayProcessor::setStateInformation (const void* data, int sizeInBytes)
{
    auto xml = getXmlFromBinary (data, sizeInBytes);

    if (xml == nullptr)
        return;

    const auto tree = juce::ValueTree::fromXml (*xml);

    if (! tree.hasType (ids::state))
        return;

    {
        const juce::ScopedLock lock (stateLock);
        trackNameOverride = tree.getProperty (ids::nameOverride, "").toString();
        hiddenTracks.clear();
        hiddenTracks.addTokens (tree.getProperty (ids::hidden, "").toString(), "\n", {});
        hiddenTracks.removeEmptyStrings();
    }

    colourOverride.store ((int) tree.getProperty (ids::colourOverride, -1));
    view.topDb.store ((float) tree.getProperty (ids::topDb, 6.0f));
    view.bottomDb.store ((float) tree.getProperty (ids::bottomDb, -84.0f));
    view.tiltDbPerOctave.store ((float) tree.getProperty (ids::tilt, 3.0f));
    view.fillOwnCurve.store ((bool) tree.getProperty (ids::fill, true));
    view.soloThisTrack.store ((bool) tree.getProperty (ids::solo, false));
}

juce::AudioProcessorEditor* SpectrumOverlayProcessor::createEditor()
{
    return new SpectrumOverlayEditor (*this);
}

} // namespace lso

//==============================================================================
juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new lso::SpectrumOverlayProcessor();
}
