#pragma once

#include "DisplayTrack.h"

#include "../core/CollisionFinder.h"

#include <functional>
#include <vector>

namespace lso
{

juce::Colour colourForSeverity (CollisionSeverity severity);
juce::String nameForSeverity (CollisionSeverity severity);

/** The overlaps, worst first: which two tracks are competing, over what band,
    and how strongly.
*/
class CollisionListView final : public juce::Component
{
public:
    static constexpr int rowHeight = 38;

    CollisionListView();

    void setContent (const std::vector<DisplayTrack>& newTracks, const std::vector<Collision>& newCollisions);
    int getPreferredHeight() const { return juce::jmax (rowHeight, rowHeight * (int) collisions.size()); }

    /** Row clicked: show only the two tracks involved. */
    std::function<void (int)> onIsolatePair;
    std::function<void (int)> onHoverChanged;

    void setHoveredRow (int row);

    void paint (juce::Graphics& g) override;
    void mouseDown (const juce::MouseEvent& event) override;
    void mouseMove (const juce::MouseEvent& event) override;
    void mouseExit (const juce::MouseEvent& event) override;

private:
    int rowAt (juce::Point<float> position) const;

    std::vector<DisplayTrack> tracks;
    std::vector<Collision> collisions;
    int hoveredRow = -1;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (CollisionListView)
};

} // namespace lso
