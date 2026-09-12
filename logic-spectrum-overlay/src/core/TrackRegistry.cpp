#include "TrackRegistry.h"

#include <algorithm>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <new>
#include <random>
#include <vector>
#include <type_traits>

#include <fcntl.h>
#include <sys/file.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

namespace lso
{

std::string TrackFrame::getName() const
{
    const auto length = strnlen (name, kNameBytes);
    return std::string (name, length);
}

void TrackFrame::setName (const std::string& newName)
{
    std::memset (name, 0, kNameBytes);
    const auto length = std::min (newName.size(), (size_t) (kNameBytes - 1));
    std::memcpy (name, newName.data(), length);
}

Appearance chooseAppearance (const std::vector<TrackFrame>& others, int numHues)
{
    const auto hues = (uint32_t) std::max (1, numHues);

    for (uint32_t style = 0; style < 64; ++style)
    {
        for (uint32_t colour = 0; colour < hues; ++colour)
        {
            const auto taken = std::any_of (others.begin(), others.end(),
                                            [colour, style] (const TrackFrame& f)
                                            {
                                                return f.colourIndex == colour && f.styleIndex == style;
                                            });

            if (! taken)
                return { colour, style };
        }
    }

    return {};
}

namespace
{
struct alignas (64) SharedSlot
{
    std::atomic<uint32_t> sequence;
    std::atomic<uint32_t> unused;
    std::atomic<uint64_t> owner;
    std::atomic<uint64_t> heartbeatMs;
    TrackFrame frame;
};

static_assert (std::atomic<uint32_t>::is_always_lock_free,
               "the registry is shared between processes, so its atomics must be lock-free");
static_assert (std::atomic<uint64_t>::is_always_lock_free,
               "the registry is shared between processes, so its atomics must be lock-free");
static_assert (std::is_trivially_copyable<TrackFrame>::value,
               "TrackFrame is memcpy'd in and out of shared memory");

bool makeParentDirectories (const std::string& path)
{
    const auto slash = path.find_last_of ('/');

    if (slash == std::string::npos || slash == 0)
        return true;

    const auto directory = path.substr (0, slash);
    std::string partial;

    for (size_t i = 1; i <= directory.size(); ++i)
    {
        if (i == directory.size() || directory[i] == '/')
        {
            partial = directory.substr (0, i);

            if (mkdir (partial.c_str(), 0700) != 0 && errno != EEXIST)
                return false;
        }
    }

    return true;
}
} // namespace

struct TrackRegistry::SharedRegistry
{
    std::atomic<uint32_t> magic;
    std::atomic<uint32_t> version;
    std::atomic<uint32_t> numSlots;
    std::atomic<uint32_t> numBins;
    SharedSlot slots[kMaxSlots];
};

TrackRegistry::~TrackRegistry()
{
    close();
}

uint64_t TrackRegistry::nowMs() noexcept
{
    using namespace std::chrono;
    return (uint64_t) duration_cast<milliseconds> (steady_clock::now().time_since_epoch()).count();
}

uint64_t TrackRegistry::makeInstanceId() noexcept
{
    std::random_device rd;
    const auto random = ((uint64_t) rd() << 32) ^ (uint64_t) rd();
    const auto pid = (uint64_t) getpid() << 48;
    return (random ^ pid ^ nowMs()) | 1u;   // never zero: zero means "free"
}

std::vector<std::string> TrackRegistry::getCandidatePaths()
{
    std::vector<std::string> paths;

    if (const auto* fromEnvironment = std::getenv ("LSO_REGISTRY_PATH"))
        paths.emplace_back (fromEnvironment);

    const auto* home = std::getenv ("HOME");

#if defined (__APPLE__)
    if (home != nullptr)
        paths.emplace_back (std::string (home) + "/Library/Application Support/LogicSpectrumOverlay/registry-v1.bin");
#else
    if (const auto* runtimeDir = std::getenv ("XDG_RUNTIME_DIR"))
        paths.emplace_back (std::string (runtimeDir) + "/logic-spectrum-overlay/registry-v1.bin");

    if (home != nullptr)
        paths.emplace_back (std::string (home) + "/.cache/logic-spectrum-overlay/registry-v1.bin");
#endif

    paths.emplace_back ("/tmp/logic-spectrum-overlay/registry-v1.bin");

    if (const auto* temporaryDir = std::getenv ("TMPDIR"))
        paths.emplace_back (std::string (temporaryDir) + "/logic-spectrum-overlay-registry-v1.bin");

    return paths;
}

std::string TrackRegistry::getDefaultPath()
{
    const auto candidates = getCandidatePaths();
    return candidates.empty() ? std::string() : candidates.front();
}

bool TrackRegistry::openDefault (std::string* errorOut)
{
    std::string firstError;

    for (const auto& candidate : getCandidatePaths())
    {
        std::string error;

        if (open (candidate, &error))
            return true;

        if (firstError.empty())
            firstError = error;
    }

    lastError = firstError.empty() ? "no usable location for the shared registry" : firstError;

    if (errorOut != nullptr)
        *errorOut = lastError;

    return false;
}

bool TrackRegistry::open (const std::string& path, std::string* errorOut)
{
    close();

    auto fail = [this, errorOut] (const std::string& message)
    {
        lastError = message + " (" + std::strerror (errno) + ")";

        if (errorOut != nullptr)
            *errorOut = lastError;

        close();
        return false;
    };

    if (! makeParentDirectories (path))
        return fail ("could not create the registry directory");

    fileDescriptor = ::open (path.c_str(), O_RDWR | O_CREAT, 0600);

    if (fileDescriptor < 0)
        return fail ("could not open the registry file");

    mappingSize = sizeof (SharedRegistry);

    // One writer at a time may size and initialise the file.
    if (flock (fileDescriptor, LOCK_EX) != 0)
        return fail ("could not lock the registry file");

    struct stat info {};

    if (fstat (fileDescriptor, &info) != 0)
    {
        flock (fileDescriptor, LOCK_UN);
        return fail ("could not stat the registry file");
    }

    if ((size_t) info.st_size < mappingSize && ftruncate (fileDescriptor, (off_t) mappingSize) != 0)
    {
        flock (fileDescriptor, LOCK_UN);
        return fail ("could not size the registry file");
    }

    mapping = mmap (nullptr, mappingSize, PROT_READ | PROT_WRITE, MAP_SHARED, fileDescriptor, 0);

    if (mapping == MAP_FAILED)
    {
        mapping = nullptr;
        flock (fileDescriptor, LOCK_UN);
        return fail ("could not map the registry file");
    }

    auto* candidate = reinterpret_cast<SharedRegistry*> (mapping);
    const auto magic = candidate->magic.load (std::memory_order_acquire);
    const auto version = candidate->version.load (std::memory_order_acquire);

    if (magic != kRegistryMagic || version != kRegistryVersion)
    {
        // Either brand new (zero-filled) or written by an older build: start over.
        registry = new (mapping) SharedRegistry();
        registry->version.store (kRegistryVersion, std::memory_order_relaxed);
        registry->numSlots.store ((uint32_t) kMaxSlots, std::memory_order_relaxed);
        registry->numBins.store ((uint32_t) kNumBins, std::memory_order_relaxed);
        registry->magic.store (kRegistryMagic, std::memory_order_release);
    }
    else
    {
        registry = candidate;
    }

    flock (fileDescriptor, LOCK_UN);
    openPath = path;
    lastError.clear();
    return true;
}

void TrackRegistry::close()
{
    releaseSlot();

    if (mapping != nullptr)
    {
        munmap (mapping, mappingSize);
        mapping = nullptr;
    }

    if (fileDescriptor >= 0)
    {
        ::close (fileDescriptor);
        fileDescriptor = -1;
    }

    registry = nullptr;
    mappingSize = 0;
    openPath.clear();
}

bool TrackRegistry::claimSlot (uint64_t instanceId)
{
    if (registry == nullptr || instanceId == 0)
        return false;

    releaseSlot();

    auto take = [this, instanceId] (int index, uint64_t expected)
    {
        auto& slot = registry->slots[index];

        if (! slot.owner.compare_exchange_strong (expected, instanceId,
                                                  std::memory_order_acq_rel,
                                                  std::memory_order_relaxed))
            return false;

        slotIndex = index;
        ownerId = instanceId;

        TrackFrame blank;
        blank.instanceId = instanceId;
        publish (blank);
        return true;
    };

    for (int i = 0; i < kMaxSlots; ++i)
        if (take (i, 0))
            return true;

    // Nothing free: take over a slot whose owner stopped beating long ago.
    const auto now = nowMs();

    for (int i = 0; i < kMaxSlots; ++i)
    {
        auto& slot = registry->slots[i];
        const auto heartbeat = slot.heartbeatMs.load (std::memory_order_acquire);
        const auto owner = slot.owner.load (std::memory_order_acquire);

        if (owner != 0 && now > heartbeat && now - heartbeat > kReclaimAfterMs && take (i, owner))
            return true;
    }

    lastError = "the registry is full";
    return false;
}

void TrackRegistry::releaseSlot()
{
    if (registry == nullptr || slotIndex < 0)
    {
        slotIndex = -1;
        ownerId = 0;
        return;
    }

    auto& slot = registry->slots[slotIndex];
    slot.heartbeatMs.store (0, std::memory_order_release);
    slot.owner.store (0, std::memory_order_release);

    slotIndex = -1;
    ownerId = 0;
}

void TrackRegistry::publish (const TrackFrame& frame)
{
    if (registry == nullptr || slotIndex < 0)
        return;

    auto& slot = registry->slots[slotIndex];

    // Seqlock: an odd sequence tells readers a write is in flight.
    const auto sequence = slot.sequence.load (std::memory_order_relaxed);
    slot.sequence.store (sequence + 1, std::memory_order_release);
    std::atomic_thread_fence (std::memory_order_release);

    std::memcpy (&slot.frame, &frame, sizeof (TrackFrame));
    slot.frame.instanceId = ownerId;

    std::atomic_thread_fence (std::memory_order_release);
    slot.sequence.store (sequence + 2, std::memory_order_release);
    slot.heartbeatMs.store (nowMs(), std::memory_order_release);
}

void TrackRegistry::readAll (std::vector<TrackFrame>& out, uint64_t now) const
{
    out.clear();

    if (registry == nullptr)
        return;

    if (now == 0)
        now = nowMs();

    for (int i = 0; i < kMaxSlots; ++i)
    {
        const auto& slot = registry->slots[i];

        if (slot.owner.load (std::memory_order_acquire) == 0)
            continue;

        const auto heartbeat = slot.heartbeatMs.load (std::memory_order_acquire);

        if (heartbeat == 0 || (now > heartbeat && now - heartbeat > kStaleAfterMs))
            continue;

        for (int attempt = 0; attempt < 8; ++attempt)
        {
            const auto before = slot.sequence.load (std::memory_order_acquire);

            if ((before & 1u) != 0)
                continue;

            TrackFrame frame;
            std::memcpy (&frame, &slot.frame, sizeof (TrackFrame));
            std::atomic_thread_fence (std::memory_order_acquire);

            if (slot.sequence.load (std::memory_order_acquire) == before)
            {
                if (frame.instanceId != 0)
                    out.push_back (frame);

                break;
            }
        }
    }
}

bool TrackRegistry::appearanceClashesWithOlderTrack (const Appearance& appearance, uint64_t now) const
{
    if (registry == nullptr || slotIndex <= 0)
        return false;

    if (now == 0)
        now = nowMs();

    for (int i = 0; i < slotIndex; ++i)
    {
        const auto& slot = registry->slots[i];

        if (slot.owner.load (std::memory_order_acquire) == 0)
            continue;

        const auto heartbeat = slot.heartbeatMs.load (std::memory_order_acquire);

        if (heartbeat == 0 || (now > heartbeat && now - heartbeat > kStaleAfterMs))
            continue;

        if (slot.frame.colourIndex == appearance.colourIndex
            && slot.frame.styleIndex == appearance.styleIndex)
            return true;
    }

    return false;
}

} // namespace lso
