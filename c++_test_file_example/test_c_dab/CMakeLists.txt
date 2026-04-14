include(FetchContent)

message("Fetching httplib and nlohmann_json dependencies...")

FetchContent_Declare(
  httplib
  GIT_REPOSITORY https://github.com/yhirose/cpp-httplib.git
  GIT_TAG v0.41.0
)

FetchContent_Declare(
  nlohmann_json
  GIT_REPOSITORY https://github.com/nlohmann/json.git
  GIT_TAG v3.12.0
)

FetchContent_MakeAvailable(httplib)
FetchContent_MakeAvailable(nlohmann_json)

file(GLOB_RECURSE TEST_SOURCES *.cpp) 

add_executable(test_c_dab_session ${TEST_SOURCES})

target_link_libraries(test_c_dab_session
    PRIVATE 
    nlohmann_json::nlohmann_json
    httplib::httplib
    radio_core_static 
    radio_api_c_static
)