#pragma once

#include "PluginProcessor.h"
#include "CollisionListView.h"
#include "SpectrumView.h"
#include "TrackListView.h"

namespace lso
{

class SpectrumOverlayEditor final : public juce::AudioProcessorEditor,
                                    private juce::Timer
{
public:
    explicit SpectrumOverlayEditor (SpectrumOverlayProcessor& processorToUse);
    ~SpectrumOverlayEditor() override;

    void paint (juce::Graphics& g) override;
    void resized() override;

private:
    void timerCallback() override;
    void rebuildDisplayTracks();
    void applyRangeSelection();
    void applyTiltSelection();
    void setAllHidden (bool hidden);
    void showOnlyThisTrack();
    void showOverlapsPanel (bool shouldShowOverlaps);
    void recomputeCollisions();
    void isolatePair (int collisionIndex);
    void highlightPair (int collisionIndex);

    SpectrumOverlayProcessor& processor;

    SpectrumView spectrumView;
    TrackListView trackList;
    CollisionListView collisionList;
    juce::Viewport listViewport;
    juce::TextButton tracksTabButton { "Tracks" }, overlapsTabButton { "Overlaps" };
    bool showingOverlaps = false;

    juce::Label titleLabel { {}, "SPECTRUM OVERLAY" };
    juce::TextEditor nameEditor;
    juce::ComboBox rangeBox, tiltBox, sensitivityBox;
    juce::ToggleButton fillButton { "Fill" };
    juce::TextButton showAllButton { "All" }, hideAllButton { "None" }, onlyMineButton { "Mine" };
    juce::Label statusLabel;

    std::vector<TrackFrame> frames;
    std::vector<DisplayTrack> displayTracks;
    std::vector<Collision> collisions;
    std::vector<int> visibleTrackIndices;
    std::vector<const float*> collisionInput;
    std::vector<float> binCentresHz;
    int ticksUntilCollisionScan = 0;
    size_t lastVisibleCount = 0;
    juce::String lastShownName;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (SpectrumOverlayEditor)
};

} // namespace lso
