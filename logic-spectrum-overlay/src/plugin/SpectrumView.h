#pragma once

#include "DisplayTrack.h"

#include "../core/CollisionFinder.h"

#include <functional>
#include <vector>

namespace lso
{

/** The overlay itself: every visible track's spectrum on one log-frequency,
    single-dB-scale plot, with a crosshair readout.
*/
class SpectrumView final : public juce::Component
{
public:
    SpectrumView();

    void setTracks (const std::vector<DisplayTrack>& newTracks);
    void setCollisions (const std::vector<Collision>& newCollisions);
    void setHighlightedTrack (int index);
    void setHighlightedTracks (std::vector<int> indices);

    /** Draws one overlap's band across the plot and names the pair. */
    void setFocusedCollision (int index);

    /** Fired when the pointer moves over the overlap strip. */
    std::function<void (int)> onCollisionHovered;
    void setRange (float newTopDb, float newBottomDb);
    void setFillOwnCurve (bool shouldFill);

    void paint (juce::Graphics& g) override;
    void mouseMove (const juce::MouseEvent& event) override;
    void mouseExit (const juce::MouseEvent& event) override;

private:
    juce::Rectangle<float> getPlotBounds() const;
    juce::Rectangle<float> getRibbonBounds() const;
    bool isDimmed (int trackIndex) const;
    int collisionAtX (float x) const;
    float xForFrequency (float hz, juce::Rectangle<float> plot) const;
    float frequencyForX (float x, juce::Rectangle<float> plot) const;
    float yForDb (float db, juce::Rectangle<float> plot) const;

    void paintGrid (juce::Graphics& g, juce::Rectangle<float> plot) const;
    void paintCurves (juce::Graphics& g, juce::Rectangle<float> plot) const;
    void paintDirectLabels (juce::Graphics& g, juce::Rectangle<float> plot) const;
    void paintRibbon (juce::Graphics& g, juce::Rectangle<float> ribbon) const;
    void paintFocusedCollision (juce::Graphics& g, juce::Rectangle<float> plot) const;
    void paintReadout (juce::Graphics& g, juce::Rectangle<float> plot) const;
    void paintEmptyState (juce::Graphics& g, juce::Rectangle<float> plot) const;

    std::vector<DisplayTrack> tracks;
    std::vector<Collision> collisions;
    std::array<float, (size_t) kNumBins> binCentres {};

    std::vector<int> highlightedTracks;
    int focusedCollision = -1;
    bool focusCameFromRibbon = false;
    float topDb = 6.0f;
    float bottomDb = -84.0f;
    bool fillOwnCurve = true;

    juce::Point<float> mousePosition;
    bool mouseIsOver = false;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (SpectrumView)
};

} // namespace lso
