#include "PluginEditor.h"

namespace lso
{

namespace
{
struct RangePreset
{
    const char* label;
    float topDb, bottomDb;
};

const RangePreset kRangePresets[] = {
    { "Range 60 dB", 6.0f, -54.0f },
    { "Range 90 dB", 6.0f, -84.0f },
    { "Range 120 dB", 6.0f, -114.0f }
};

struct TiltPreset
{
    const char* label;
    float dbPerOctave;
};

const TiltPreset kTiltPresets[] = {
    { "Tilt off", 0.0f },
    { "Tilt 3 dB/oct", 3.0f },
    { "Tilt 4.5 dB/oct", 4.5f },
    { "Tilt 6 dB/oct", 6.0f }
};

int closestPresetId (float value, const float* candidates, int numCandidates)
{
    auto best = 0;

    for (int i = 1; i < numCandidates; ++i)
        if (std::abs (candidates[i] - value) < std::abs (candidates[best] - value))
            best = i;

    return best + 1;
}
} // namespace

SpectrumOverlayEditor::SpectrumOverlayEditor (SpectrumOverlayProcessor& processorToUse)
    : AudioProcessorEditor (&processorToUse), processor (processorToUse)
{
    titleLabel.setFont (juce::FontOptions (12.0f, juce::Font::bold));
    titleLabel.setColour (juce::Label::textColourId, toJuceColour (kTextMuted));
    addAndMakeVisible (titleLabel);

    nameEditor.setMultiLine (false);
    nameEditor.setFont (juce::FontOptions (13.0f));
    nameEditor.setColour (juce::TextEditor::backgroundColourId, toJuceColour (kSurfaceRaised));
    nameEditor.setColour (juce::TextEditor::outlineColourId, toJuceColour (kGridLine));
    nameEditor.setColour (juce::TextEditor::focusedOutlineColourId, toJuceColour (kGridLineStrong));
    nameEditor.setColour (juce::TextEditor::textColourId, toJuceColour (kTextPrimary));
    nameEditor.setTooltip ("The name this track publishes under. Clear it to follow Logic's track name.");
    nameEditor.onReturnKey = [this]
    {
        processor.setTrackNameOverride (nameEditor.getText());
        nameEditor.giveAwayKeyboardFocus();
    };
    nameEditor.onFocusLost = [this] { processor.setTrackNameOverride (nameEditor.getText()); };
    addAndMakeVisible (nameEditor);

    auto styleBox = [this] (juce::ComboBox& box)
    {
        box.setColour (juce::ComboBox::backgroundColourId, toJuceColour (kSurfaceRaised));
        box.setColour (juce::ComboBox::outlineColourId, toJuceColour (kGridLine));
        box.setColour (juce::ComboBox::textColourId, toJuceColour (kTextSecondary));
        box.setColour (juce::ComboBox::arrowColourId, toJuceColour (kTextMuted));
        addAndMakeVisible (box);
    };

    for (int i = 0; i < (int) std::size (kRangePresets); ++i)
        rangeBox.addItem (kRangePresets[i].label, i + 1);

    for (int i = 0; i < (int) std::size (kTiltPresets); ++i)
        tiltBox.addItem (kTiltPresets[i].label, i + 1);

    styleBox (rangeBox);
    styleBox (tiltBox);

    const float rangeValues[] = { kRangePresets[0].bottomDb, kRangePresets[1].bottomDb, kRangePresets[2].bottomDb };
    const float tiltValues[] = { kTiltPresets[0].dbPerOctave, kTiltPresets[1].dbPerOctave,
                                 kTiltPresets[2].dbPerOctave, kTiltPresets[3].dbPerOctave };

    rangeBox.setSelectedId (closestPresetId (processor.view.bottomDb.load(), rangeValues, 3),
                            juce::dontSendNotification);
    tiltBox.setSelectedId (closestPresetId (processor.view.tiltDbPerOctave.load(), tiltValues, 4),
                           juce::dontSendNotification);

    rangeBox.onChange = [this] { applyRangeSelection(); };
    tiltBox.onChange = [this] { applyTiltSelection(); };

    fillButton.setColour (juce::ToggleButton::textColourId, toJuceColour (kTextSecondary));
    fillButton.setColour (juce::ToggleButton::tickColourId, toJuceColour (kTextPrimary));
    fillButton.setColour (juce::ToggleButton::tickDisabledColourId, toJuceColour (kGridLineStrong));
    fillButton.setToggleState (processor.view.fillOwnCurve.load(), juce::dontSendNotification);
    fillButton.setTooltip ("Shade the area under this track's own curve.");
    fillButton.onClick = [this]
    {
        processor.view.fillOwnCurve.store (fillButton.getToggleState());
        spectrumView.setFillOwnCurve (fillButton.getToggleState());
    };
    addAndMakeVisible (fillButton);

    auto styleButton = [this] (juce::TextButton& button, const juce::String& tooltip)
    {
        button.setColour (juce::TextButton::buttonColourId, toJuceColour (kSurfaceRaised));
        button.setColour (juce::TextButton::textColourOffId, toJuceColour (kTextSecondary));
        button.setTooltip (tooltip);
        addAndMakeVisible (button);
    };

    styleButton (showAllButton, "Show every track");
    styleButton (hideAllButton, "Hide every track");
    styleButton (onlyMineButton, "Show only this track");

    showAllButton.onClick = [this] { setAllHidden (false); };
    hideAllButton.onClick = [this] { setAllHidden (true); };
    onlyMineButton.onClick = [this] { showOnlyThisTrack(); };

    trackListViewport.setViewedComponent (&trackList, false);
    trackListViewport.setScrollBarsShown (true, false);
    addAndMakeVisible (trackListViewport);

    trackList.onToggleVisibility = [this] (int row)
    {
        if (! juce::isPositiveAndBelow (row, (int) displayTracks.size()))
            return;

        const auto& track = displayTracks[(size_t) row];
        processor.setTrackHidden (track.name, track.visible);

        // Hiding your own track while soloing it would leave nothing on screen.
        if (track.isOwn && processor.view.soloThisTrack.load())
            processor.view.soloThisTrack.store (false);

        rebuildDisplayTracks();
    };

    trackList.onHoverChanged = [this] (int row) { spectrumView.setHighlightedTrack (row); };

    trackList.onCycleColour = [this] (int row)
    {
        if (! juce::isPositiveAndBelow (row, (int) displayTracks.size()))
            return;

        const auto current = processor.getColourOverride();
        const auto next = current < 0 ? 0 : current + 1;
        processor.setColourOverride (next >= kNumHues ? -1 : next);
    };

    statusLabel.setFont (juce::FontOptions (10.0f));
    statusLabel.setColour (juce::Label::textColourId, toJuceColour (kTextMuted));
    addAndMakeVisible (statusLabel);

    addAndMakeVisible (spectrumView);
    spectrumView.setFillOwnCurve (processor.view.fillOwnCurve.load());
    applyRangeSelection();

    setResizable (true, true);
    setResizeLimits (620, 380, 2600, 1700);
    setSize (940, 560);

    startTimerHz (30);
}

SpectrumOverlayEditor::~SpectrumOverlayEditor()
{
    stopTimer();
}

//==============================================================================
void SpectrumOverlayEditor::applyRangeSelection()
{
    const auto index = juce::jlimit (0, (int) std::size (kRangePresets) - 1, rangeBox.getSelectedId() - 1);
    processor.view.topDb.store (kRangePresets[index].topDb);
    processor.view.bottomDb.store (kRangePresets[index].bottomDb);
    spectrumView.setRange (kRangePresets[index].topDb, kRangePresets[index].bottomDb);
}

void SpectrumOverlayEditor::applyTiltSelection()
{
    const auto index = juce::jlimit (0, (int) std::size (kTiltPresets) - 1, tiltBox.getSelectedId() - 1);
    processor.view.tiltDbPerOctave.store (kTiltPresets[index].dbPerOctave);
}

void SpectrumOverlayEditor::setAllHidden (bool hidden)
{
    processor.view.soloThisTrack.store (false);

    if (! hidden)
    {
        processor.setHiddenTracks ({});
        rebuildDisplayTracks();
        return;
    }

    juce::StringArray names;

    for (const auto& track : displayTracks)
        names.addIfNotAlreadyThere (track.name);

    processor.setHiddenTracks (names);
    rebuildDisplayTracks();
}

void SpectrumOverlayEditor::showOnlyThisTrack()
{
    processor.view.soloThisTrack.store (! processor.view.soloThisTrack.load());
    rebuildDisplayTracks();
}

//==============================================================================
void SpectrumOverlayEditor::timerCallback()
{
    rebuildDisplayTracks();

    const auto name = processor.getTrackName();

    if (name != lastShownName && ! nameEditor.hasKeyboardFocus (true))
    {
        lastShownName = name;
        nameEditor.setText (name, juce::dontSendNotification);
    }
}

void SpectrumOverlayEditor::rebuildDisplayTracks()
{
    processor.getLiveTracks (frames);

    const auto ownId = processor.getInstanceId();
    const auto solo = processor.view.soloThisTrack.load();

    displayTracks.clear();
    displayTracks.reserve (frames.size());

    for (const auto& frame : frames)
    {
        DisplayTrack track;
        track.name = juce::String (frame.getName());
        track.colour = toJuceColour (hueForIndex ((int) frame.colourIndex));
        track.styleIndex = (int) frame.styleIndex;
        track.isOwn = frame.instanceId == ownId;
        track.hasSignal = (frame.flags & trackFlagHasSignal) != 0;
        track.peakDb = frame.peakDb;
        track.visible = ! processor.isTrackHidden (track.name) && (! solo || track.isOwn);

        for (int i = 0; i < kNumBins; ++i)
            track.bins[(size_t) i] = frame.bins[i];

        displayTracks.push_back (std::move (track));
    }

    spectrumView.setTracks (displayTracks);
    trackList.setTracks (displayTracks);
    trackList.setSize (trackListViewport.getWidth(), trackList.getPreferredHeight());

    const auto visible = std::count_if (displayTracks.begin(), displayTracks.end(),
                                        [] (const DisplayTrack& track) { return track.visible; });

    statusLabel.setText (juce::String ((int) visible) + " of " + juce::String ((int) displayTracks.size())
                             + " tracks shown  " + juce::String::charToString ((juce::juce_wchar) 0x00b7)
                             + "  " + processor.getRegistryStatus(),
                         juce::dontSendNotification);

    onlyMineButton.setColour (juce::TextButton::buttonColourId,
                              toJuceColour (solo ? kGridLineStrong : kSurfaceRaised));
}

//==============================================================================
void SpectrumOverlayEditor::paint (juce::Graphics& g)
{
    g.fillAll (juce::Colour::fromRGB (0x10, 0x10, 0x0f));
}

void SpectrumOverlayEditor::resized()
{
    auto area = getLocalBounds().reduced (8);

    auto header = area.removeFromTop (26);
    titleLabel.setBounds (header.removeFromLeft (140));
    header.removeFromLeft (4);
    nameEditor.setBounds (header.removeFromLeft (juce::jmin (220, header.getWidth() / 3)).reduced (0, 1));
    tiltBox.setBounds (header.removeFromRight (130).reduced (2, 1));
    rangeBox.setBounds (header.removeFromRight (110).reduced (2, 1));
    fillButton.setBounds (header.removeFromRight (60).reduced (2, 0));

    area.removeFromTop (6);
    statusLabel.setBounds (area.removeFromBottom (16));
    area.removeFromBottom (4);

    auto listArea = area.removeFromRight (juce::jlimit (180, 260, area.getWidth() / 4));
    area.removeFromRight (8);

    auto listHeader = listArea.removeFromTop (22);
    const auto buttonWidth = listHeader.getWidth() / 3;
    showAllButton.setBounds (listHeader.removeFromLeft (buttonWidth).reduced (1));
    hideAllButton.setBounds (listHeader.removeFromLeft (buttonWidth).reduced (1));
    onlyMineButton.setBounds (listHeader.reduced (1));

    listArea.removeFromTop (4);
    trackListViewport.setBounds (listArea);
    trackList.setSize (listArea.getWidth(), trackList.getPreferredHeight());

    spectrumView.setBounds (area);
}

} // namespace lso
