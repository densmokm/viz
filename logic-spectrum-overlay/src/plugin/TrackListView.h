#pragma once

#include "DisplayTrack.h"

#include <functional>
#include <vector>

namespace lso
{

/** The legend, and the show/hide control: one row per publishing track. */
class TrackListView final : public juce::Component
{
public:
    static constexpr int rowHeight = 26;

    TrackListView();

    void setTracks (const std::vector<DisplayTrack>& newTracks);
    int getPreferredHeight() const { return juce::jmax (rowHeight, rowHeight * (int) tracks.size()); }

    std::function<void (int)> onToggleVisibility;
    std::function<void (int)> onHoverChanged;
    std::function<void (int)> onCycleColour;

    void paint (juce::Graphics& g) override;
    void mouseDown (const juce::MouseEvent& event) override;
    void mouseMove (const juce::MouseEvent& event) override;
    void mouseExit (const juce::MouseEvent& event) override;

private:
    int rowAt (juce::Point<float> position) const;
    void setHoveredRow (int row);

    std::vector<DisplayTrack> tracks;
    int hoveredRow = -1;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (TrackListView)
};

} // namespace lso
