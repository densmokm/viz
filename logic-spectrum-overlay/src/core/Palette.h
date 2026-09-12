#pragma once

#include <cstdint>

namespace lso
{

struct Rgb
{
    uint8_t r = 0, g = 0, b = 0;
};

/** Categorical hues, in fixed assignment order, stepped for a dark surface.

    These are the validated dark-mode steps of the reference categorical
    palette: worst adjacent-pair separation 8.4 CVD / 19.3 normal-vision
    (OKLab x100). The order is the colourblind-safety mechanism, so hues are
    handed out in it and never re-ordered or generated.
*/
inline constexpr int kNumHues = 8;

/** Line styles used as secondary encoding once every hue is in use, so a
    session with more than eight tracks still reads unambiguously.
*/
enum class LineStyle
{
    solid = 0,
    dashed,
    dotted,
    dotDash
};

inline constexpr int kNumLineStyles = 4;

Rgb hueForIndex (int index) noexcept;
const char* hueName (int index) noexcept;
LineStyle styleForIndex (int index) noexcept;
const char* styleName (int index) noexcept;

/** Chart surfaces and ink, dark mode. */
inline constexpr Rgb kSurface { 0x1a, 0x1a, 0x19 };
inline constexpr Rgb kSurfaceRaised { 0x24, 0x24, 0x22 };
inline constexpr Rgb kGridLine { 0x33, 0x33, 0x30 };
inline constexpr Rgb kGridLineStrong { 0x45, 0x45, 0x41 };
inline constexpr Rgb kTextPrimary { 0xff, 0xff, 0xff };
inline constexpr Rgb kTextSecondary { 0xc3, 0xc2, 0xb7 };
inline constexpr Rgb kTextMuted { 0x8a, 0x89, 0x80 };

} // namespace lso
