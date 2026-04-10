#pragma once

#include <httplib.h>

#include <mutex>
#include <nlohmann/json.hpp>
#include <optional>
#include <string>
#include <unordered_map>

using json = nlohmann::json;

using CallBackType = std::string;
using GroupId = std::string;
using RequestId = std::string;

struct PendingRequest {
  CallBackType callback_type;
  GroupId group_id;
  RequestId request_id;
};

struct CallbackMessage {
  CallBackType callback_type;
  GroupId group_id;
  RequestId request_id;
  std::string status;
  std::string timestamp;
  json payload;
};

inline auto& get_pending_requests() {
  static std::unordered_map<std::string, PendingRequest> g_pending_requests;
  return g_pending_requests;
}

inline void set_pending_request(const std::string& key, const json& request) {
  get_pending_requests()[key] = PendingRequest{
      .callback_type = request.value("callback_type", ""),
      .group_id = request.value("group_id", ""),
      .request_id = request.value("request_id", ""),
  };
}

inline json get_callback_message(const std::string& key, const json& payload) {
  auto it = get_pending_requests().find(key);
  if (it == get_pending_requests().end()) {
    throw std::runtime_error("No pending request found for key: " + key);
  }

  const auto& pending = it->second;
  return json{
      {"callback_type", pending.callback_type},
      {"group_id", pending.group_id},
      {"request_id", pending.request_id},
      {"status", "success"},
      {"timestamp", std::to_string(std::time(nullptr))},
      {"payload", payload},
  };
}

class HttpClient {
 public:
  static std::optional<json> Get(const std::string& path) {
    return getInstance().getImpl(path);
  }

  static bool Post(const std::string& path, const json& data) {
    return getInstance().postImpl(path, data);
  }

  static void SetBaseUrl(const std::string& url) {
    std::lock_guard<std::mutex> lock(getInstance().mutex_);
    getInstance().cli_ = httplib::Client(url);
    getInstance().configureClient();
  }

  HttpClient(const HttpClient&) = delete;
  HttpClient& operator=(const HttpClient&) = delete;
  HttpClient(HttpClient&&) = delete;
  HttpClient& operator=(HttpClient&&) = delete;

 private:
  explicit HttpClient(const std::string& url) : cli_(url) { configureClient(); }
  ~HttpClient() = default;

  static HttpClient& getInstance() {
    static HttpClient instance("http://localhost:8090");
    return instance;
  }

  void configureClient() {
    cli_.set_connection_timeout(5, 0);
    cli_.set_read_timeout(10, 0);
    headers_ = {
        {"Accept", "application/json"},
        {"User-Agent", "MyRadioSystem-Backend/1.0"},
        {"keep-alive", "true"},
    };
  }

  std::optional<json> getImpl(const std::string& path) {
    if (auto res = cli_.Get(path, headers_)) {
      if (res->status == 200) {
        try {
          return json::parse(res->body);
        } catch (const json::parse_error& e) {
          return std::nullopt;
        }
      }
    }
    return std::nullopt;
  }

  bool postImpl(const std::string& path, const json& data) {
    if (auto res = cli_.Post(path, headers_, data.dump(), "application/json")) {
      return res->status == 200 || res->status == 201;
    }
    return false;
  }

  httplib::Client cli_;
  httplib::Headers headers_;
  std::mutex mutex_;
};