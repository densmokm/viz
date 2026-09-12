#include "Fft.h"

#include <cmath>

namespace lso
{

Fft::Fft (int orderIn)
    : order (orderIn), fftSize (1 << orderIn)
{
    bitReversal.resize ((size_t) fftSize);

    for (int i = 0; i < fftSize; ++i)
    {
        int reversed = 0;

        for (int bit = 0; bit < order; ++bit)
            if ((i & (1 << bit)) != 0)
                reversed |= 1 << (order - 1 - bit);

        bitReversal[(size_t) i] = reversed;
    }

    // Twiddles for the largest stage; smaller stages stride through the table.
    twiddleRe.resize ((size_t) (fftSize / 2));
    twiddleIm.resize ((size_t) (fftSize / 2));

    for (int i = 0; i < fftSize / 2; ++i)
    {
        const auto angle = -2.0 * M_PI * (double) i / (double) fftSize;
        twiddleRe[(size_t) i] = (float) std::cos (angle);
        twiddleIm[(size_t) i] = (float) std::sin (angle);
    }
}

void Fft::forward (float* re, float* im) const noexcept
{
    for (int i = 0; i < fftSize; ++i)
    {
        const auto j = bitReversal[(size_t) i];

        if (j > i)
        {
            std::swap (re[i], re[j]);
            std::swap (im[i], im[j]);
        }
    }

    for (int len = 2; len <= fftSize; len <<= 1)
    {
        const auto half = len / 2;
        const auto stride = fftSize / len;

        for (int start = 0; start < fftSize; start += len)
        {
            for (int k = 0; k < half; ++k)
            {
                const auto wr = twiddleRe[(size_t) (k * stride)];
                const auto wi = twiddleIm[(size_t) (k * stride)];

                const auto a = start + k;
                const auto b = a + half;

                const auto tr = re[b] * wr - im[b] * wi;
                const auto ti = re[b] * wi + im[b] * wr;

                re[b] = re[a] - tr;
                im[b] = im[a] - ti;
                re[a] += tr;
                im[a] += ti;
            }
        }
    }
}

} // namespace lso
