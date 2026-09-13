cmake_minimum_required (VERSION 3.22)

project (LogicSpectrumOverlay VERSION 0.1.0 LANGUAGES C CXX)

set (CMAKE_CXX_STANDARD 17)
set (CMAKE_CXX_STANDARD_REQUIRED ON)

if (APPLE)
    set (CMAKE_OSX_ARCHITECTURES "arm64;x86_64" CACHE STRING "Build a universal binary so Logic loads it natively on both Apple silicon and Intel")
    set (CMAKE_OSX_DEPLOYMENT_TARGET "11.0" CACHE STRING "Minimum macOS version")
endif ()

option (LSO_BUILD_PLUGIN "Build the audio plugin (downloads JUCE)" ON)
option (LSO_BUILD_TESTS "Build the framework-free core tests" ON)

#==============================================================================
# The analysis and sharing core. No framework dependency, so it can be tested
# anywhere, including on a build machine with no plugin host.
#==============================================================================
add_library (lso_core STATIC
    src/core/CollisionFinder.cpp
    src/core/Fft.cpp
    src/core/Palette.cpp
    src/core/SpectrumAnalyser.cpp
    src/core/TrackRegistry.cpp)

target_include_directories (lso_core PUBLIC src)
target_compile_features (lso_core PUBLIC cxx_std_17)

find_package (Threads REQUIRED)
target_link_libraries (lso_core PUBLIC Threads::Threads)

if (MSVC)
    target_compile_options (lso_core PRIVATE /W4)
else ()
    target_compile_options (lso_core PRIVATE -Wall -Wextra)
endif ()

#==============================================================================
if (LSO_BUILD_TESTS)
    enable_testing ()

    add_executable (lso_core_tests tests/CoreTests.cpp)
    target_link_libraries (lso_core_tests PRIVATE lso_core)

    add_test (NAME core COMMAND lso_core_tests)
endif ()

#==============================================================================
if (LSO_BUILD_PLUGIN)
    include (FetchContent)

    FetchContent_Declare (JUCE
        GIT_REPOSITORY https://github.com/juce-framework/JUCE.git
        GIT_TAG 8.0.15
        GIT_SHALLOW TRUE)

    FetchContent_MakeAvailable (JUCE)

    if (APPLE)
        set (LSO_FORMATS AU VST3 Standalone)
    else ()
        set (LSO_FORMATS VST3 Standalone)
    endif ()

    juce_add_plugin (SpectrumOverlay
        PRODUCT_NAME "Spectrum Overlay"
        COMPANY_NAME "Kevin Densmore"
        BUNDLE_ID "com.kevindensmore.spectrumoverlay"
        PLUGIN_MANUFACTURER_CODE Kdns
        PLUGIN_CODE Lsov
        FORMATS ${LSO_FORMATS}
        AU_MAIN_TYPE kAudioUnitType_Effect
        IS_SYNTH FALSE
        NEEDS_MIDI_INPUT FALSE
        NEEDS_MIDI_OUTPUT FALSE
        IS_MIDI_EFFECT FALSE
        EDITOR_WANTS_KEYBOARD_FOCUS TRUE
        COPY_PLUGIN_AFTER_BUILD TRUE)

    target_sources (SpectrumOverlay PRIVATE
        src/plugin/CollisionListView.cpp
        src/plugin/PluginProcessor.cpp
        src/plugin/PluginEditor.cpp
        src/plugin/SpectrumView.cpp
        src/plugin/TrackListView.cpp)

    target_compile_definitions (SpectrumOverlay PUBLIC
        JUCE_WEB_BROWSER=0
        JUCE_USE_CURL=0
        JUCE_VST3_CAN_REPLACE_VST2=0
        JUCE_DISPLAY_SPLASH_SCREEN=0
        JUCE_REPORT_APP_USAGE=0)

    target_link_libraries (SpectrumOverlay
        PRIVATE
            lso_core
            juce::juce_audio_utils
        PUBLIC
            juce::juce_recommended_config_flags
            juce::juce_recommended_lto_flags
            juce::juce_recommended_warning_flags)

    # A headless harness that runs several instances at once and renders the
    # real editor to PNG - the plugin UI can then be reviewed without a host.
    juce_add_console_app (lso_preview PRODUCT_NAME "lso-preview")

    target_sources (lso_preview PRIVATE
        tools/RenderPreview.cpp
        src/plugin/CollisionListView.cpp
        src/plugin/PluginProcessor.cpp
        src/plugin/PluginEditor.cpp
        src/plugin/SpectrumView.cpp
        src/plugin/TrackListView.cpp)

    target_compile_definitions (lso_preview PUBLIC
        JUCE_WEB_BROWSER=0
        JUCE_USE_CURL=0
        JUCE_MODAL_LOOPS_PERMITTED=1
        JUCE_STANDALONE_APPLICATION=1)

    target_link_libraries (lso_preview
        PRIVATE
            lso_core
            juce::juce_audio_utils
        PUBLIC
            juce::juce_recommended_config_flags
            juce::juce_recommended_warning_flags)
endif ()
