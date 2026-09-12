#pragma once

#include <juce_gui_basics/juce_gui_basics.h>

#include <array>

#include "../core/Palette.h"
#include "../core/TrackRegistry.h"

namespace lso
{

/** One track as the UI needs it: what the registry published, resolved into
    colours and visibility.
*/
struct DisplayTrack
{
    juce::String name;
    juce::Colour colour;
    int styleIndex = 0;
    bool isOwn = false;
    bool visible = true;
    bool hasSignal = false;
    float peakDb = -120.0f;
    std::array<float, (size_t) kNumBins> bins {};
};

inline juce::Colour toJuceColour (Rgb rgb)
{
    return juce::Colour::fromRGB (rgb.r, rgb.g, rgb.b);
}

} // namespace lso
