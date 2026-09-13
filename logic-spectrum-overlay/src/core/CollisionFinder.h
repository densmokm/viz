#pragma once

#include <vector>

namespace lso
{

/** How loud, how wide and how close two tracks have to be before an overlap is
    worth pointing at.
*/
struct CollisionSettings
{
    /** Both tracks must be within this much of *their own* loudest point.

        Without this, two broadband tracks overlap across the whole spectrum -
        which is true and useless. What makes a mix decision is both tracks
        being near their own strong region at the same frequency.
    */
    float prominenceDb = 9.0f;
    /** Ignore anything this far below the loudest point on screen. */
    float relativeFloorDb = 30.0f;
    /** ...and ignore anything below this outright. */
    float absoluteFloorDb = -72.0f;
    /** Once inside a band, stay in it until it falls this far past the
        entry conditions, so one dip does not split a band in two. */
    float hysteresisDb = 4.0f;
    /** Coincidences narrower than this are not worth a mix decision. */
    int minimumBins = 5;
};

enum class CollisionSeverity
{
    moderate = 0,
    strong,
    severe
};

/** A frequency band where two tracks are both strongly present. */
struct Collision
{
    int trackA = 0;
    int trackB = 0;
    int firstBin = 0;
    int lastBin = 0;
    float lowHz = 0.0f;
    float highHz = 0.0f;
    float peakHz = 0.0f;
    /** The loudest point at which both tracks are present: the level of the
        quieter track there, which is what makes the overlap audible. */
    float strengthDb = -120.0f;
    float widthOctaves = 0.0f;
    CollisionSeverity severity = CollisionSeverity::moderate;

    bool coversBin (int bin) const { return bin >= firstBin && bin <= lastBin; }
};

/** Finds the bands where visible tracks compete for the same frequencies.

    Only the worst band per pair is returned: the list is a triage tool, and a
    pair listed three times buries the pair below it.

    Overlap is measured as the level of the *quieter* of the two tracks: if one
    track is 40 dB down on the other they are not fighting, whatever else they
    share. Results come back strongest first.

    @param tracks        one bin array per track, each `numBins` long
    @param binCentresHz  the frequency of each bin
    @param maxResults    0 for no limit
*/
std::vector<Collision> findCollisions (const std::vector<const float*>& tracks,
                                       const std::vector<float>& binCentresHz,
                                       const CollisionSettings& settings = {},
                                       int maxResults = 0);

/** The strongest overlap covering a bin, or nullptr. */
const Collision* strongestCollisionAt (const std::vector<Collision>& collisions, int bin);

} // namespace lso
