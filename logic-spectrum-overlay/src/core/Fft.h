#pragma once

#include <vector>

namespace lso
{

/** Minimal in-place iterative radix-2 complex FFT.

    Deliberately free of any framework dependency so the analysis core can be
    unit-tested on any platform, including the CI box, without a plugin host.
*/
class Fft
{
public:
    explicit Fft (int orderIn);

    int getSize() const noexcept { return fftSize; }
    int getOrder() const noexcept { return order; }

    /** Forward transform, in place. re/im must each hold getSize() floats. */
    void forward (float* re, float* im) const noexcept;

private:
    int order = 0;
    int fftSize = 0;
    std::vector<int> bitReversal;
    std::vector<float> twiddleRe, twiddleIm;
};

} // namespace lso
