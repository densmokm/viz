#include "TrackListView.h"

namespace lso
{

TrackListView::TrackListView()
{
    setInterceptsMouseClicks (true, false);
}

void TrackListView::setTracks (const std::vector<DisplayTrack>& newTracks)
{
    const auto countChanged = newTracks.size() != tracks.size();
    tracks = newTracks;

    if (countChanged)
    {
        setSize (getWidth(), getPreferredHeight());

        if (hoveredRow >= (int) tracks.size())
            setHoveredRow (-1);
    }

    repaint();
}

int TrackListView::rowAt (juce::Point<float> position) const
{
    const auto row = (int) (position.y / (float) rowHeight);
    return juce::isPositiveAndBelow (row, (int) tracks.size()) ? row : -1;
}

void TrackListView::setHoveredRow (int row)
{
    if (hoveredRow == row)
        return;

    hoveredRow = row;

    if (onHoverChanged != nullptr)
        onHoverChanged (row);

    repaint();
}

void TrackListView::paint (juce::Graphics& g)
{
    for (int i = 0; i < (int) tracks.size(); ++i)
    {
        const auto& track = tracks[(size_t) i];
        const auto row = juce::Rectangle<float> (0.0f, (float) (i * rowHeight), (float) getWidth(), (float) rowHeight);

        if (i == hoveredRow)
        {
            g.setColour (toJuceColour (kSurfaceRaised));
            g.fillRoundedRectangle (row.reduced (2.0f, 1.0f), 3.0f);
        }

        // Visibility: a filled dot for shown, an outline for hidden, so the
        // state is readable without relying on the colour swatch.
        const auto dot = juce::Rectangle<float> (7.0f, row.getCentreY() - 4.0f, 8.0f, 8.0f);

        if (track.visible)
        {
            g.setColour (toJuceColour (kTextPrimary));
            g.fillEllipse (dot);
        }
        else
        {
            g.setColour (toJuceColour (kTextMuted));
            g.drawEllipse (dot, 1.2f);
        }

        auto swatch = juce::Rectangle<float> (23.0f, row.getCentreY() - 1.0f, 20.0f, 2.0f);
        juce::Path line;
        line.startNewSubPath (swatch.getX(), swatch.getCentreY());
        line.lineTo (swatch.getRight(), swatch.getCentreY());

        const juce::PathStrokeType stroke (2.0f);
        g.setColour (track.colour.withAlpha (track.visible ? 1.0f : 0.35f));

        switch (styleForIndex (track.styleIndex))
        {
            case LineStyle::solid:
                g.strokePath (line, stroke);
                break;

            case LineStyle::dashed:
            {
                const float dashes[] = { 6.0f, 4.0f };
                juce::Path dashed;
                stroke.createDashedStroke (dashed, line, dashes, 2);
                g.fillPath (dashed);
                break;
            }

            case LineStyle::dotted:
            {
                const float dashes[] = { 2.0f, 3.0f };
                juce::Path dashed;
                stroke.createDashedStroke (dashed, line, dashes, 2);
                g.fillPath (dashed);
                break;
            }

            case LineStyle::dotDash:
            {
                const float dashes[] = { 8.0f, 3.0f, 2.0f, 3.0f };
                juce::Path dashed;
                stroke.createDashedStroke (dashed, line, dashes, 4);
                g.fillPath (dashed);
                break;
            }
        }

        g.setFont (juce::FontOptions (12.0f, track.isOwn ? juce::Font::bold : juce::Font::plain));
        g.setColour (toJuceColour (track.visible ? (track.isOwn ? kTextPrimary : kTextSecondary) : kTextMuted));
        g.drawText (track.name + (track.isOwn ? "  (this track)" : ""),
                    row.withTrimmedLeft (50.0f).withTrimmedRight (46.0f),
                    juce::Justification::centredLeft, true);

        g.setFont (juce::FontOptions (11.0f));
        g.setColour (toJuceColour (track.hasSignal ? kTextSecondary : kTextMuted));
        g.drawText (track.hasSignal ? juce::String (track.peakDb, 1) : juce::String ("--"),
                    row.withTrimmedRight (8.0f), juce::Justification::centredRight);
    }
}

void TrackListView::mouseDown (const juce::MouseEvent& event)
{
    const auto row = rowAt (event.position);

    if (row < 0)
        return;

    // The swatch is the colour control for your own track; the rest of the row
    // toggles whether the track is drawn.
    if (event.position.x < 46.0f && event.position.x > 20.0f
        && tracks[(size_t) row].isOwn && onCycleColour != nullptr)
    {
        onCycleColour (row);
        return;
    }

    if (onToggleVisibility != nullptr)
        onToggleVisibility (row);
}

void TrackListView::mouseMove (const juce::MouseEvent& event)
{
    setHoveredRow (rowAt (event.position));
}

void TrackListView::mouseExit (const juce::MouseEvent&)
{
    setHoveredRow (-1);
}

} // namespace lso
