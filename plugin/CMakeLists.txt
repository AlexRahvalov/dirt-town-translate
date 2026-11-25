cmake_minimum_required(VERSION 3.20)
project(dirt_town_locale_plugin LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_library(version SHARED
    src/main.cpp
    version.def
)

set_target_properties(version PROPERTIES
    OUTPUT_NAME "version"
    PREFIX ""
    SUFFIX ".dll"
)

if(MSVC)
    target_compile_options(version PRIVATE /W4 /O2 /MT /utf-8)
    target_compile_definitions(version PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX _CRT_SECURE_NO_WARNINGS)
endif()
