#include <unistd.h>

#include <condition_variable>
#include <cstdio>
#include <iostream>
#include <mutex>
#include <sstream>
#include <unordered_map>

#include "c_dab_session.h"
#include "http_client.h"
#include "http_server.h"

using Autolock = std::unique_lock<std::mutex>;

inline constexpr const char* kHostPort = "localhost:8090";
inline constexpr const char* kCallbackPrefix = "/callback/v1";
inline constexpr const char* kControlPrefix = "/control/v1";

struct LOG {
  LOG() {}
  ~LOG() { std::cout << oss_.str() << std::endl; }

  template <typename T>
  LOG& operator<<(const T& value) {
    oss_ << value;
    return *this;
  }

 private:
  std::ostringstream oss_;
};

// static dab_ensemble s_target_ensemble;
static dab_select_entry s_select_result_entry;

// Callback data structure for testing
using test_callback_data = struct test_callback_data {
  bool status_received;
  dab_status last_status;

  std::mutex mutex;
  std::condition_variable cond;

  bool program_list_received;
  size_t ensemble_count;
  int program_list_complete_count = 0;

  bool select_service_success;

  bool dynamic_label_received;
  int dynamic_label_length;

  bool slide_show_received;
  std::string slide_show_mime_type;
  int slide_show_length;

  bool announcement_received;
  bool announcement_on;

  bool rssi_received;
  int8_t rssi_value;

  bool fm_link_received;
  bool fm_on;
};

extern "C" {
void status_callback(dab_status status, void* userdata) {
  auto* data = reinterpret_cast<test_callback_data*>(userdata);
  data->status_received = true;
  data->last_status = status;
}

void program_list_callback(dab_ensemble* ensemble_list, size_t ensemble_count,
                           bool completed, bool background, void* userdata) {
  auto* data = reinterpret_cast<test_callback_data*>(userdata);

  if (completed) {
    data->program_list_received = true;
    data->ensemble_count = ensemble_count;

    if (ensemble_count > 0) {
      json callback_message =
          get_callback_message("scan", {
                                           {"message", "Scan completed"},
                                           {"ensemble_count", ensemble_count},
                                       });

      HttpClient::Post(std::string(kCallbackPrefix) + "/scan",
                       callback_message);
    }

    data->program_list_complete_count++;
    {
      Autolock _lk(data->mutex);
      data->cond.notify_all();
    }
  }
}

void select_result_callback(const dab_select_entry* entry, bool success,
                            bool isPlayed, void* userdata) {
  auto* data = reinterpret_cast<test_callback_data*>(userdata);
  data->select_service_success = success;
  s_select_result_entry = *entry;
  LOG() << "select service " << (success ? "success " : "failed ")
        << entry->frequency << " " << entry->service_id << " "
        << entry->component_id;
}

void dynamic_label_callback(const uint8_t* data, int length, void* userdata) {
  auto* cb_data = reinterpret_cast<test_callback_data*>(userdata);
  cb_data->dynamic_label_received = true;
  cb_data->dynamic_label_length = length;
}

void slide_show_callback(const char* mime_type, const uint8_t* data, int length,
                         void* userdata) {
  auto* cb_data = reinterpret_cast<test_callback_data*>(userdata);
  cb_data->slide_show_received = true;
  if (mime_type) {
    cb_data->slide_show_mime_type = mime_type;
  }
  cb_data->slide_show_length = length;
}

void announcement_callback(uint16_t asw, bool announcement_on, void* userdata) {
  auto* cb_data = reinterpret_cast<test_callback_data*>(userdata);
  cb_data->announcement_received = true;
  cb_data->announcement_on = announcement_on;
}

void rssi_callback(int8_t rssi, void* userdata) {
  auto* cb_data = reinterpret_cast<test_callback_data*>(userdata);
  cb_data->rssi_received = true;
  cb_data->rssi_value = rssi;
}

void fm_link_callback(bool fm_on, void* userdata) {
  auto* cb_data = reinterpret_cast<test_callback_data*>(userdata);
  cb_data->fm_link_received = true;
  cb_data->fm_on = fm_on;
}
}

struct DABObject {
  DABObject() {}

  void init() {
    session_ = dab_session_create();
    dab_session_set_listener(session_, &listener_);
    dab_session_open(session_);

    HttpClient::Post(std::string(kControlPrefix) + "/start",
                     {{"message", "DAB session initialized"}});
  }

  ~DABObject() {
    if (session_) {
      dab_session_close(session_);
      dab_session_destroy(session_);
      session_ = nullptr;
    }
  }

  dab_session* session_ = nullptr;
  test_callback_data cb_data_ = {0};
  dab_session_listener listener_ = {
      .status_cb = status_callback,
      .program_list_cb = program_list_callback,
      .select_result_cb = select_result_callback,
      .dynamic_label_cb = dynamic_label_callback,
      .slide_show_cb = slide_show_callback,
      .announcement_cb = announcement_callback,
      .rssi_cb = rssi_callback,
      .fm_link_cb = fm_link_callback,
      .userdata = &cb_data_,
  };
};

static DABObject dab_obj;

void do_scan_command(const std::vector<std::string>& args, bool background) {
  dab_session_scan(dab_obj.session_, background);
}

void do_deselect_command(const std::vector<std::string>& args) {
}

/* ---------------------------- Server Router API --------------------------- */
json handle_scan(const json& request) {
  bool background = request.value("background", true);

  set_pending_request("scan", request);
  do_scan_command({}, background);
  return {{"status", "scan started"}, {"background", background}};
}
/* ---------------------------- Server Router API --------------------------- */

int main(int /*argc*/, char* /*argv*/[]) {
  HttpServer server("0.0.0.0", 8000);

  /* ---------------------------- add server routes ---------------------------
   */
  server.addRoute("/scan", handle_scan);
  /* ---------------------------- add server routes ---------------------------
   */

  dab_obj.init();

  server.start();

  return 0;
}