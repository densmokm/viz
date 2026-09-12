#include "SpectrumView.h"

#include "../core/SpectrumAnalyser.h"

#include <algorithm>
#include <cmath>

namespace lso
{

namespace
{
constexpr float kMinHz = 20.0f;
constexpr float kMaxHz = 20000.0f;

const float kGridFrequencies[] = { 20.0f, 30.0f, 40.0f, 50.0f, 60.0f, 80.0f,
                                   100.0f, 200.0f, 300.0f, 400.0f, 500.0f, 600.0f, 800.0f,
                                   1000.0f, 2000.0f, 3000.0f, 4000.0f, 5000.0f, 6000.0f, 8000.0f,
                                   10000.0f, 20000.0f };

const float kLabelledFrequencies[] = { 50.0f, 100.0f, 200.0f, 500.0f, 1000.0f, 2000.0f, 5000.0f, 10000.0f };

bool isLabelled (float hz)
{
    for (auto candidate : kLabelledFrequencies)
        if (juce::approximatelyEqual (candidate, hz))
            return true;

    return false;
}

bool isDecade (float hz)
{
    return juce::approximatelyEqual (hz, 100.0f) || juce::approximatelyEqual (hz, 1000.0f)
           || juce::approximatelyEqual (hz, 10000.0f);
}

juce::String formatFrequency (float hz)
{
    if (hz < 1000.0f)
        return juce::String (juce::roundToInt (hz)) + " Hz";

    const auto kHz = hz / 1000.0f;

    if (kHz >= 10.0f)
        return juce::String (juce::roundToInt (kHz)) + " kHz";

    // Trim a trailing ".0" without eating a significant zero.
    auto text = juce::String (kHz, 1);

    if (text.endsWith (".0"))
        text = text.dropLastCharacters (2);

    return text + " kHz";
}

/** A middle dot, built from its code point rather than from raw bytes in a
    source literal.
*/
const juce::String& separator()
{
    static const juce::String dot = "  " + juce::String::charToString ((juce::juce_wchar) 0x00b7) + "  ";
    return dot;
}

juce::String noteNameForFrequency (float hz)
{
    if (hz < 16.0f)
        return {};

    static const char* names[] = { "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B" };
    const auto midi = juce::roundToInt (69.0 + 12.0 * std::log2 ((double) hz / 440.0));
    return juce::String (names[((midi % 12) + 12) % 12]) + juce::String (midi / 12 - 1);
}

void strokeWithStyle (juce::Graphics& g, const juce::Path& path, int styleIndex, float thickness)
{
    const juce::PathStrokeType stroke (thickness, juce::PathStrokeType::curved, juce::PathStrokeType::rounded);

    switch (styleForIndex (styleIndex))
    {
        case LineStyle::solid:
            g.strokePath (path, stroke);
            return;

        case LineStyle::dashed:
        {
            const float dashes[] = { 9.0f, 5.0f };
            juce::Path dashed;
            stroke.createDashedStroke (dashed, path, dashes, 2);
            g.fillPath (dashed);
            return;
        }

        case LineStyle::dotted:
        {
            const float dashes[] = { 2.0f, 4.0f };
            juce::Path dashed;
            stroke.createDashedStroke (dashed, path, dashes, 2);
            g.fillPath (dashed);
            return;
        }

        case LineStyle::dotDash:
        {
            const float dashes[] = { 10.0f, 4.0f, 2.0f, 4.0f };
            juce::Path dashed;
            stroke.createDashedStroke (dashed, path, dashes, 4);
            g.fillPath (dashed);
            return;
        }
    }
}

/** A short line in the track's own style, used wherever a label needs a mark
    beside it rather than coloured text.
*/
void drawStyleSwatch (juce::Graphics& g, juce::Rectangle<float> area, juce::Colour colour, int styleIndex)
{
    juce::Path line;
    line.startNewSubPath (area.getX(), area.getCentreY());
    line.lineTo (area.getRight(), area.getCentreY());

    g.setColour (colour);
    strokeWithStyle (g, line, styleIndex, 2.0f);
}
} // namespace

//==============================================================================
SpectrumView::SpectrumView()
{
    for (int i = 0; i < kNumBins; ++i)
        binCentres[(size_t) i] = SpectrumAnalyser::binCentreHz (i, kNumBins, kMinHz, kMaxHz);

    setInterceptsMouseClicks (true, false);
}

void SpectrumView::setTracks (const std::vector<DisplayTrack>& newTracks)
{
    tracks = newTracks;
    repaint();
}

void SpectrumView::setHighlightedTrack (int index)
{
    if (highlightedTrack == index)
        return;

    highlightedTrack = index;
    repaint();
}

void SpectrumView::setRange (float newTopDb, float newBottomDb)
{
    if (juce::approximatelyEqual (topDb, newTopDb) && juce::approximatelyEqual (bottomDb, newBottomDb))
        return;

    topDb = newTopDb;
    bottomDb = newBottomDb;
    repaint();
}

void SpectrumView::setFillOwnCurve (bool shouldFill)
{
    if (fillOwnCurve == shouldFill)
        return;

    fillOwnCurve = shouldFill;
    repaint();
}

//==============================================================================
juce::Rectangle<float> SpectrumView::getPlotBounds() const
{
    return getLocalBounds().toFloat().reduced (2.0f).withTrimmedBottom (18.0f).withTrimmedRight (34.0f);
}

float SpectrumView::xForFrequency (float hz, juce::Rectangle<float> plot) const
{
    const auto position = std::log (hz / kMinHz) / std::log (kMaxHz / kMinHz);
    return plot.getX() + plot.getWidth() * juce::jlimit (0.0f, 1.0f, (float) position);
}

float SpectrumView::frequencyForX (float x, juce::Rectangle<float> plot) const
{
    const auto position = juce::jlimit (0.0f, 1.0f, (x - plot.getX()) / juce::jmax (1.0f, plot.getWidth()));
    return kMinHz * std::pow (kMaxHz / kMinHz, position);
}

float SpectrumView::yForDb (float db, juce::Rectangle<float> plot) const
{
    const auto position = (db - bottomDb) / juce::jmax (1.0f, topDb - bottomDb);
    return plot.getBottom() - plot.getHeight() * juce::jlimit (-0.1f, 1.1f, position);
}

//==============================================================================
void SpectrumView::paint (juce::Graphics& g)
{
    const auto plot = getPlotBounds();

    g.setColour (toJuceColour (kSurface));
    g.fillRoundedRectangle (getLocalBounds().toFloat(), 4.0f);

    paintGrid (g, plot);

    const auto anyVisible = std::any_of (tracks.begin(), tracks.end(),
                                         [] (const DisplayTrack& track) { return track.visible; });

    if (! anyVisible)
    {
        paintEmptyState (g, plot);
        return;
    }

    {
        const juce::Graphics::ScopedSaveState saved (g);
        g.reduceClipRegion (plot.toNearestInt());
        paintCurves (g, plot);
    }

    paintDirectLabels (g, plot);

    if (mouseIsOver && plot.contains (mousePosition))
        paintReadout (g, plot);
}

void SpectrumView::paintGrid (juce::Graphics& g, juce::Rectangle<float> plot) const
{
    g.setFont (juce::FontOptions (11.0f));

    for (auto hz : kGridFrequencies)
    {
        const auto x = xForFrequency (hz, plot);
        g.setColour (toJuceColour (isDecade (hz) ? kGridLineStrong : kGridLine));
        g.drawVerticalLine (juce::roundToInt (x), plot.getY(), plot.getBottom());

        if (isLabelled (hz))
        {
            g.setColour (toJuceColour (kTextMuted));
            g.drawText (formatFrequency (hz),
                        juce::Rectangle<float> (x - 30.0f, plot.getBottom() + 2.0f, 60.0f, 14.0f),
                        juce::Justification::centred);
        }
    }

    for (auto db = std::ceil (topDb / 12.0f) * 12.0f; db >= bottomDb; db -= 12.0f)
    {
        const auto y = yForDb (db, plot);

        if (y < plot.getY() || y > plot.getBottom())
            continue;

        g.setColour (toJuceColour (juce::approximatelyEqual (db, 0.0f) ? kGridLineStrong : kGridLine));
        g.drawHorizontalLine (juce::roundToInt (y), plot.getX(), plot.getRight());

        g.setColour (toJuceColour (kTextMuted));
        g.drawText (juce::String (juce::roundToInt (db)),
                    juce::Rectangle<float> (plot.getRight() + 3.0f, y - 7.0f, 30.0f, 14.0f),
                    juce::Justification::centredLeft);
    }
}

void SpectrumView::paintCurves (juce::Graphics& g, juce::Rectangle<float> plot) const
{
    auto buildPath = [this, plot] (const DisplayTrack& track)
    {
        juce::Path path;

        for (int i = 0; i < kNumBins; ++i)
        {
            const auto x = xForFrequency (binCentres[(size_t) i], plot);
            const auto y = yForDb (track.bins[(size_t) i], plot);

            if (i == 0)
                path.startNewSubPath (x, y);
            else
                path.lineTo (x, y);
        }

        return path;
    };

    // Everything else first, so this track's own curve is never hidden behind
    // another, and the highlighted track sits on top of all of them.
    auto drawTrack = [&] (int index, const DisplayTrack& track)
    {
        if (! track.visible)
            return;

        const auto dimmed = highlightedTrack >= 0 && highlightedTrack != index;
        const auto alpha = dimmed ? 0.22f : 1.0f;
        const auto path = buildPath (track);

        if (track.isOwn && fillOwnCurve && ! dimmed)
        {
            juce::Path filled (path);
            filled.lineTo (plot.getRight(), plot.getBottom() + 2.0f);
            filled.lineTo (plot.getX(), plot.getBottom() + 2.0f);
            filled.closeSubPath();

            g.setGradientFill (juce::ColourGradient (track.colour.withAlpha (0.26f), plot.getX(), plot.getY(),
                                                     track.colour.withAlpha (0.02f), plot.getX(), plot.getBottom(),
                                                     false));
            g.fillPath (filled);
        }

        g.setColour (track.colour.withAlpha (alpha));
        strokeWithStyle (g, path, track.styleIndex, track.isOwn ? 2.6f : 2.0f);
    };

    for (int i = 0; i < (int) tracks.size(); ++i)
        if (! tracks[(size_t) i].isOwn && i != highlightedTrack)
            drawTrack (i, tracks[(size_t) i]);

    for (int i = 0; i < (int) tracks.size(); ++i)
        if (tracks[(size_t) i].isOwn && i != highlightedTrack)
            drawTrack (i, tracks[(size_t) i]);

    if (highlightedTrack >= 0 && highlightedTrack < (int) tracks.size())
        drawTrack (highlightedTrack, tracks[(size_t) highlightedTrack]);
}

void SpectrumView::paintDirectLabels (juce::Graphics& g, juce::Rectangle<float> plot) const
{
    // With a handful of tracks on screen, name them on the plot as well as in
    // the list, so identity never rests on colour alone.
    std::vector<int> visible;

    for (int i = 0; i < (int) tracks.size(); ++i)
        if (tracks[(size_t) i].visible && tracks[(size_t) i].hasSignal)
            visible.push_back (i);

    if (visible.empty() || visible.size() > 4)
        return;

    g.setFont (juce::FontOptions (11.0f));
    std::vector<float> usedYs;

    for (auto index : visible)
    {
        const auto& track = tracks[(size_t) index];

        auto peakBin = 0;

        for (int i = 1; i < kNumBins; ++i)
            if (track.bins[(size_t) i] > track.bins[(size_t) peakBin])
                peakBin = i;

        auto x = xForFrequency (binCentres[(size_t) peakBin], plot);
        auto y = yForDb (track.bins[(size_t) peakBin], plot) - 14.0f;

        // Nudge labels apart rather than letting them collide.
        for (auto usedY : usedYs)
            if (std::abs (usedY - y) < 14.0f)
                y = usedY - 15.0f;

        usedYs.push_back (y);

        const auto width = juce::GlyphArrangement::getStringWidth (juce::FontOptions (11.0f), track.name) + 22.0f;
        x = juce::jlimit (plot.getX(), plot.getRight() - width, x - width * 0.5f);
        y = juce::jlimit (plot.getY(), plot.getBottom() - 14.0f, y);

        const juce::Rectangle<float> label (x, y, width, 14.0f);

        g.setColour (toJuceColour (kSurface).withAlpha (0.82f));
        g.fillRoundedRectangle (label, 3.0f);

        drawStyleSwatch (g, label.withWidth (14.0f).reduced (3.0f, 0.0f), track.colour, track.styleIndex);

        g.setColour (toJuceColour (kTextPrimary));
        g.drawText (track.name, label.withTrimmedLeft (16.0f), juce::Justification::centredLeft);
    }
}

void SpectrumView::paintReadout (juce::Graphics& g, juce::Rectangle<float> plot) const
{
    const auto hz = frequencyForX (mousePosition.x, plot);

    g.setColour (toJuceColour (kGridLineStrong));
    g.drawVerticalLine (juce::roundToInt (mousePosition.x), plot.getY(), plot.getBottom());

    // Nearest bin to the cursor, read off every visible track.
    auto nearestBin = 0;

    for (int i = 1; i < kNumBins; ++i)
        if (std::abs (binCentres[(size_t) i] - hz) < std::abs (binCentres[(size_t) nearestBin] - hz))
            nearestBin = i;

    struct Reading
    {
        const DisplayTrack* track;
        float db;
    };

    std::vector<Reading> readings;

    for (const auto& track : tracks)
        if (track.visible)
            readings.push_back ({ &track, track.bins[(size_t) nearestBin] });

    std::sort (readings.begin(), readings.end(),
               [] (const Reading& a, const Reading& b) { return a.db > b.db; });

    const auto maxRows = juce::jmin ((int) readings.size(), 9);
    const auto rowHeight = 15.0f;
    const auto panelWidth = 186.0f;
    const auto panelHeight = 26.0f + rowHeight * (float) maxRows;

    auto panel = juce::Rectangle<float> (mousePosition.x + 12.0f, plot.getY() + 8.0f, panelWidth, panelHeight);

    if (panel.getRight() > plot.getRight())
        panel.setX (mousePosition.x - panelWidth - 12.0f);

    panel.setY (juce::jlimit (plot.getY(), juce::jmax (plot.getY(), plot.getBottom() - panelHeight), panel.getY()));

    g.setColour (toJuceColour (kSurfaceRaised).withAlpha (0.96f));
    g.fillRoundedRectangle (panel, 5.0f);
    g.setColour (toJuceColour (kGridLineStrong));
    g.drawRoundedRectangle (panel, 5.0f, 1.0f);

    const auto note = noteNameForFrequency (hz);
    g.setColour (toJuceColour (kTextPrimary));
    g.setFont (juce::FontOptions (12.0f, juce::Font::bold));
    g.drawText (formatFrequency (hz) + (note.isEmpty() ? juce::String() : separator() + note),
                panel.reduced (8.0f, 4.0f).withHeight (18.0f), juce::Justification::centredLeft);

    g.setFont (juce::FontOptions (11.0f));

    for (int i = 0; i < maxRows; ++i)
    {
        const auto& reading = readings[(size_t) i];
        const auto row = juce::Rectangle<float> (panel.getX() + 8.0f, panel.getY() + 24.0f + rowHeight * (float) i,
                                                 panel.getWidth() - 16.0f, rowHeight);

        drawStyleSwatch (g, row.withWidth (14.0f).reduced (0.0f, 1.0f), reading.track->colour, reading.track->styleIndex);

        g.setColour (toJuceColour (reading.track->isOwn ? kTextPrimary : kTextSecondary));
        g.drawText (reading.track->name, row.withTrimmedLeft (19.0f).withTrimmedRight (46.0f),
                    juce::Justification::centredLeft, true);

        g.setColour (toJuceColour (reading.db > bottomDb + 1.0f ? kTextPrimary : kTextMuted));
        g.drawText (reading.db <= bottomDb + 0.5f ? juce::String ("--")
                                                  : juce::String (reading.db, 1) + " dB",
                    row.withTrimmedLeft (row.getWidth() - 44.0f), juce::Justification::centredRight);
    }
}

void SpectrumView::paintEmptyState (juce::Graphics& g, juce::Rectangle<float> plot) const
{
    g.setColour (toJuceColour (kTextMuted));
    g.setFont (juce::FontOptions (13.0f));
    g.drawText (tracks.empty() ? "No tracks are publishing yet - add Spectrum Overlay to a track"
                               : "Every track is hidden - switch one back on in the list",
                plot, juce::Justification::centred);
}

//==============================================================================
void SpectrumView::mouseMove (const juce::MouseEvent& event)
{
    mousePosition = event.position;
    mouseIsOver = true;
    repaint();
}

void SpectrumView::mouseExit (const juce::MouseEvent&)
{
    mouseIsOver = false;
    repaint();
}

} // namespace lso
