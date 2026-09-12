#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace lso
{

inline constexpr uint32_t kRegistryMagic = 0x314F534Cu;   // "LSO1"
inline constexpr uint32_t kRegistryVersion = 1;
inline constexpr int kMaxSlots = 128;
inline constexpr int kNumBins = 192;
inline constexpr int kNameBytes = 64;

/** A slot is dropped from the display this long after its last heartbeat. */
inline constexpr uint64_t kStaleAfterMs = 2000;
/** A slot may be taken over by another instance this long after its last heartbeat. */
inline constexpr uint64_t kReclaimAfterMs = 10000;

enum TrackFlags : uint32_t
{
    trackFlagNone = 0,
    trackFlagHasSignal = 1u << 0,
    trackFlagBypassed = 1u << 1
};

/** One track's published state. Plain-old-data so it can be copied straight
    in and out of shared memory.
*/
struct TrackFrame
{
    uint64_t instanceId = 0;
    uint32_t colourIndex = 0;
    uint32_t styleIndex = 0;
    uint32_t flags = trackFlagNone;
    uint32_t reserved = 0;
    float peakDb = -120.0f;
    float rmsDb = -120.0f;
    char name[kNameBytes] = {};
    float bins[kNumBins] = {};

    std::string getName() const;
    void setName (const std::string& newName);
};

/** How a track is drawn: which categorical hue, and which line style.

    Styles are the secondary encoding that keeps identity readable once a
    session has more tracks than the palette has hues.
*/
struct Appearance
{
    uint32_t colourIndex = 0;
    uint32_t styleIndex = 0;

    bool operator== (const Appearance& other) const
    {
        return colourIndex == other.colourIndex && styleIndex == other.styleIndex;
    }
};

/** Picks the appearance least used by the tracks already on screen. Pure, so
    every instance derives the same answer from the same registry contents.
*/
Appearance chooseAppearance (const std::vector<TrackFrame>& others, int numHues);

/** A file-backed, lock-free registry shared by every plugin instance.

    Logic may host plugins in-process or in one of several AUHostingService
    processes, so instances cannot assume shared address space. A small
    memory-mapped file works in either case, survives a host crash, and needs
    no daemon.

    Each instance owns exactly one slot and writes only to that slot, under a
    seqlock: readers never block writers, and a torn read is detected and
    retried rather than displayed.
*/
class TrackRegistry
{
public:
    TrackRegistry() = default;
    ~TrackRegistry();

    TrackRegistry (const TrackRegistry&) = delete;
    TrackRegistry& operator= (const TrackRegistry&) = delete;

    /** Locations to try, best first. Logic is a sandboxed app, so the
        preferred location is not guaranteed to be writable; the later
        candidates keep the overlay working when it is not.
    */
    static std::vector<std::string> getCandidatePaths();
    static std::string getDefaultPath();

    bool open (const std::string& path, std::string* errorOut = nullptr);

    /** Opens the first candidate location that works. */
    bool openDefault (std::string* errorOut = nullptr);

    /** The location actually in use, once open. */
    const std::string& getPath() const noexcept { return openPath; }
    void close();
    bool isOpen() const noexcept { return registry != nullptr; }
    const std::string& getLastError() const noexcept { return lastError; }

    /** Takes ownership of a free (or long-dead) slot. */
    bool claimSlot (uint64_t instanceId);
    void releaseSlot();
    int getSlotIndex() const noexcept { return slotIndex; }

    /** Writes this instance's frame and refreshes its heartbeat. */
    void publish (const TrackFrame& frame);

    /** Every slot that has beaten recently, in slot order. */
    void readAll (std::vector<TrackFrame>& out, uint64_t nowMs = 0) const;

    /** True when a live slot with a lower index already uses this appearance,
        which is how two instances that claimed at the same moment settle.
    */
    bool appearanceClashesWithOlderTrack (const Appearance& appearance, uint64_t nowMs = 0) const;

    static uint64_t nowMs() noexcept;
    static uint64_t makeInstanceId() noexcept;

private:

    void* mapping = nullptr;
    size_t mappingSize = 0;
    int fileDescriptor = -1;
    int slotIndex = -1;
    uint64_t ownerId = 0;
    std::string openPath;
    std::string lastError;

    struct SharedRegistry;
    SharedRegistry* registry = nullptr;
};

} // namespace lso
