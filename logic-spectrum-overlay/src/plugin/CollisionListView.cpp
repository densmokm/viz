#include "CollisionListView.h"

namespace lso
{

juce::Colour colourForSeverity (CollisionSeverity severity)
{
    // The reserved status steps, never the categorical hues: an overlap is a
    // state, not another series. Always shipped with a word beside it.
    switch (severity)
    {
        case CollisionSeverity::severe:   return juce::Colour::fromRGB (0xd0, 0x3b, 0x3b);
        case CollisionSeverity::strong:   return juce::Colour::fromRGB (0xec, 0x83, 0x5a);
        case CollisionSeverity::moderate: break;
    }

    return juce::Colour::fromRGB (0xfa, 0xb2, 0x19);
}

juce::String nameForSeverity (CollisionSeverity severity)
{
    switch (severity)
    {
        case CollisionSeverity::severe:   return "severe";
        case CollisionSeverity::strong:   return "strong";
        case CollisionSeverity::moderate: break;
    }

    return "moderate";
}

namespace
{
juce::String formatHz (float hz)
{
    if (hz < 1000.0f)
        return juce::String (juce::roundToInt (hz));

    const auto kHz = hz / 1000.0f;

    if (kHz >= 10.0f)
        return juce::String (juce::roundToInt (kHz)) + "k";

    auto text = juce::String (kHz, 1);

    if (text.endsWith (".0"))
        text = text.dropLastCharacters (2);

    return text + "k";
}
} // namespace

CollisionListView::CollisionListView()
{
    setInterceptsMouseClicks (true, false);
}

void CollisionListView::setContent (const std::vector<DisplayTrack>& newTracks,
                                    const std::vector<Collision>& newCollisions)
{
    const auto countChanged = newCollisions.size() != collisions.size();

    tracks = newTracks;
    collisions = newCollisions;

    if (countChanged)
    {
        setSize (getWidth(), getPreferredHeight());

        if (hoveredRow >= (int) collisions.size())
            setHoveredRow (-1);
    }

    repaint();
}

int CollisionListView::rowAt (juce::Point<float> position) const
{
    const auto row = (int) (position.y / (float) rowHeight);
    return juce::isPositiveAndBelow (row, (int) collisions.size()) ? row : -1;
}

void CollisionListView::setHoveredRow (int row)
{
    if (hoveredRow == row)
        return;

    hoveredRow = row;

    if (onHoverChanged != nullptr)
        onHoverChanged (row);

    repaint();
}

void CollisionListView::paint (juce::Graphics& g)
{
    if (collisions.empty())
    {
        g.setColour (toJuceColour (kTextMuted));
        g.setFont (juce::FontOptions (11.0f));
        g.drawFittedText ("No tracks are competing for the same frequencies right now.",
                          getLocalBounds().reduced (8, 0).withHeight (rowHeight),
                          juce::Justification::centredLeft, 3);
        return;
    }

    for (int i = 0; i < (int) collisions.size(); ++i)
    {
        const auto& collision = collisions[(size_t) i];
        const auto row = juce::Rectangle<float> (0.0f, (float) (i * rowHeight), (float) getWidth(), (float) rowHeight);

        if (i == hoveredRow)
        {
            g.setColour (toJuceColour (kSurfaceRaised));
            g.fillRoundedRectangle (row.reduced (2.0f, 1.0f), 3.0f);
        }

        const auto severityColour = colourForSeverity (collision.severity);

        g.setColour (severityColour);
        g.fillRoundedRectangle (juce::Rectangle<float> (6.0f, row.getY() + 8.0f, 3.0f, (float) rowHeight - 16.0f), 1.5f);

        const auto textArea = row.withTrimmedLeft (15.0f).withTrimmedRight (6.0f);

        const auto headline = formatHz (collision.peakHz) + " Hz";
        const auto topRow = textArea.withHeight (17.0f).withTrimmedTop (3.0f);

        g.setColour (toJuceColour (kTextPrimary));
        g.setFont (juce::FontOptions (12.0f, juce::Font::bold));
        g.drawText (headline, topRow, juce::Justification::centredLeft, true);

        const auto headlineWidth = juce::GlyphArrangement::getStringWidth (
            juce::Font (juce::FontOptions (12.0f, juce::Font::bold)), headline);

        g.setColour (toJuceColour (kTextMuted));
        g.setFont (juce::FontOptions (10.0f));
        g.drawText (formatHz (collision.lowHz) + " - " + formatHz (collision.highHz),
                    topRow.withTrimmedLeft (headlineWidth + 6.0f).withTrimmedRight (72.0f),
                    juce::Justification::centredLeft, true);

        g.setColour (toJuceColour (kTextSecondary));
        g.setFont (juce::FontOptions (10.0f));
        g.drawText (nameForSeverity (collision.severity) + "  " + juce::String (collision.strengthDb, 1) + " dB",
                    textArea.withHeight (17.0f).withTrimmedTop (3.0f),
                    juce::Justification::centredRight, true);

        const auto nameOf = [this] (int index)
        {
            return juce::isPositiveAndBelow (index, (int) tracks.size()) ? tracks[(size_t) index].name
                                                                        : juce::String ("?");
        };

        g.setColour (toJuceColour (kTextSecondary));
        g.setFont (juce::FontOptions (11.0f));
        g.drawText (nameOf (collision.trackA) + "  vs  " + nameOf (collision.trackB),
                    textArea.withTrimmedTop (18.0f).withHeight (16.0f),
                    juce::Justification::centredLeft, true);
    }
}

void CollisionListView::mouseDown (const juce::MouseEvent& event)
{
    const auto row = rowAt (event.position);

    if (row >= 0 && onIsolatePair != nullptr)
        onIsolatePair (row);
}

void CollisionListView::mouseMove (const juce::MouseEvent& event)
{
    setHoveredRow (rowAt (event.position));
}

void CollisionListView::mouseExit (const juce::MouseEvent&)
{
    setHoveredRow (-1);
}

} // namespace lso
