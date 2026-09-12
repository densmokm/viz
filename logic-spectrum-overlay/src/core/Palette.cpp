#include "Palette.h"

namespace lso
{

namespace
{
constexpr Rgb kHues[kNumHues] = {
    { 0x39, 0x87, 0xe5 },   // blue
    { 0xd9, 0x59, 0x26 },   // orange
    { 0x19, 0x9e, 0x70 },   // aqua
    { 0xc9, 0x85, 0x00 },   // yellow
    { 0xd5, 0x51, 0x81 },   // magenta
    { 0x00, 0x83, 0x00 },   // green
    { 0x90, 0x85, 0xe9 },   // violet
    { 0xe6, 0x67, 0x67 }    // red
};

constexpr const char* kHueNames[kNumHues] = {
    "blue", "orange", "aqua", "yellow", "magenta", "green", "violet", "red"
};

constexpr const char* kStyleNames[kNumLineStyles] = {
    "solid", "dashed", "dotted", "dot-dash"
};
} // namespace

Rgb hueForIndex (int index) noexcept
{
    if (index < 0)
        index = 0;

    return kHues[index % kNumHues];
}

const char* hueName (int index) noexcept
{
    if (index < 0)
        index = 0;

    return kHueNames[index % kNumHues];
}

LineStyle styleForIndex (int index) noexcept
{
    if (index < 0)
        index = 0;

    return (LineStyle) (index % kNumLineStyles);
}

const char* styleName (int index) noexcept
{
    if (index < 0)
        index = 0;

    return kStyleNames[index % kNumLineStyles];
}

} // namespace lso
