#pragma once

#include "PluginProcessor.h"
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

    SpectrumOverlayProcessor& processor;

    SpectrumView spectrumView;
    TrackListView trackList;
    juce::Viewport trackListViewport;

    juce::Label titleLabel { {}, "SPECTRUM OVERLAY" };
    juce::TextEditor nameEditor;
    juce::ComboBox rangeBox, tiltBox;
    juce::ToggleButton fillButton { "Fill" };
    juce::TextButton showAllButton { "All" }, hideAllButton { "None" }, onlyMineButton { "Mine" };
    juce::Label statusLabel;

    std::vector<TrackFrame> frames;
    std::vector<DisplayTrack> displayTracks;
    juce::String lastShownName;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (SpectrumOverlayEditor)
};

} // namespace lso
