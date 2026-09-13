#include "CollisionFinder.h"

#include <algorithm>
#include <cmath>

namespace lso
{

namespace
{
CollisionSeverity severityFor (float strengthDb, float loudestDb)
{
    const auto below = loudestDb - strengthDb;

    if (below <= 12.0f)
        return CollisionSeverity::severe;

    if (below <= 20.0f)
        return CollisionSeverity::strong;

    return CollisionSeverity::moderate;
}
} // namespace

std::vector<Collision> findCollisions (const std::vector<const float*>& tracks,
                                       const std::vector<float>& binCentresHz,
                                       const CollisionSettings& settings,
                                       int maxResults)
{
    std::vector<Collision> collisions;

    const auto numBins = (int) binCentresHz.size();

    if (tracks.size() < 2 || numBins < 2)
        return collisions;

    auto loudest = -200.0f;

    for (const auto* bins : tracks)
        for (int i = 0; i < numBins; ++i)
            loudest = std::max (loudest, bins[i]);

    const auto enterDb = std::max (settings.absoluteFloorDb, loudest - settings.relativeFloorDb);

    // Each track's own loudest point, so prominence is judged per track.
    std::vector<float> trackPeaks (tracks.size(), -200.0f);

    for (size_t t = 0; t < tracks.size(); ++t)
        for (int i = 0; i < numBins; ++i)
            trackPeaks[t] = std::max (trackPeaks[t], tracks[t][i]);

    for (size_t a = 0; a < tracks.size(); ++a)
    {
        for (size_t b = a + 1; b < tracks.size(); ++b)
        {
            // How far inside every condition this bin sits. At or above zero
            // the two tracks are competing here.
            auto marginAt = [&] (int bin)
            {
                const auto levelA = tracks[a][bin];
                const auto levelB = tracks[b][bin];

                const auto prominenceMargin = std::min (levelA - trackPeaks[a], levelB - trackPeaks[b])
                                              + settings.prominenceDb;
                const auto audibilityMargin = std::min (levelA, levelB) - enterDb;

                return std::min (prominenceMargin, audibilityMargin);
            };

            auto runStart = -1;
            auto runPeakBin = 0;
            auto runPeakDb = -200.0f;

            auto closeRun = [&] (int endBin)
            {
                if (runStart < 0)
                    return;

                const auto bins = endBin - runStart + 1;

                if (bins >= settings.minimumBins && runPeakDb >= enterDb)
                {
                    Collision collision;
                    collision.trackA = (int) a;
                    collision.trackB = (int) b;
                    collision.firstBin = runStart;
                    collision.lastBin = endBin;
                    collision.lowHz = binCentresHz[(size_t) runStart];
                    collision.highHz = binCentresHz[(size_t) endBin];
                    collision.peakHz = binCentresHz[(size_t) runPeakBin];
                    collision.strengthDb = runPeakDb;
                    collision.widthOctaves = std::log2 (std::max (1.0f, collision.highHz)
                                                        / std::max (1.0f, collision.lowHz));
                    collision.severity = severityFor (runPeakDb, loudest);
                    collisions.push_back (collision);
                }

                runStart = -1;
                runPeakDb = -200.0f;
            };

            for (int i = 0; i < numBins; ++i)
            {
                const auto margin = marginAt (i);
                const auto shared = std::min (tracks[a][i], tracks[b][i]);

                if (runStart < 0)
                {
                    if (margin >= 0.0f)
                    {
                        runStart = i;
                        runPeakBin = i;
                        runPeakDb = shared;
                    }
                }
                else if (margin >= -settings.hysteresisDb)
                {
                    if (shared > runPeakDb)
                    {
                        runPeakDb = shared;
                        runPeakBin = i;
                    }
                }
                else
                {
                    closeRun (i - 1);
                }
            }

            closeRun (numBins - 1);
        }
    }

    std::sort (collisions.begin(), collisions.end(),
               [] (const Collision& x, const Collision& y)
               {
                   if (std::abs (x.strengthDb - y.strengthDb) >= 1.0f)
                       return x.strengthDb > y.strengthDb;

                   return x.lowHz < y.lowHz;
               });

    // One entry per pair, the worst one, since they arrive strongest first.
    std::vector<Collision> worstPerPair;
    worstPerPair.reserve (collisions.size());

    for (const auto& collision : collisions)
    {
        const auto alreadyListed = std::any_of (worstPerPair.begin(), worstPerPair.end(),
                                                [&collision] (const Collision& kept)
                                                {
                                                    return kept.trackA == collision.trackA
                                                           && kept.trackB == collision.trackB;
                                                });

        if (! alreadyListed)
            worstPerPair.push_back (collision);
    }

    collisions = std::move (worstPerPair);

    if (maxResults > 0 && (int) collisions.size() > maxResults)
        collisions.resize ((size_t) maxResults);

    return collisions;
}

const Collision* strongestCollisionAt (const std::vector<Collision>& collisions, int bin)
{
    const Collision* best = nullptr;

    for (const auto& collision : collisions)
        if (collision.coversBin (bin) && (best == nullptr || collision.strengthDb > best->strengthDb))
            best = &collision;

    return best;
}

} // namespace lso
