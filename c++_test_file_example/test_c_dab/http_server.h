#pragma once

#include <httplib.h>

#include <functional>
#include <iostream>
#include <nlohmann/json.hpp>
#include <string>

using json = nlohmann::json;

class HttpServer {
 public:
  using Handler = std::function<json(const json&)>;

  HttpServer(const std::string& host, int port) : host_(host), port_(port) {}
  ~HttpServer() { stop(); }

  HttpServer& operator=(const HttpServer&) = delete;
  HttpServer(const HttpServer&) = delete;
  HttpServer& operator=(HttpServer&&) = delete;
  HttpServer(HttpServer&&) = delete;

  void addRoute(const std::string& path, const Handler& handler) {
    server_.Post(path, [handler](const httplib::Request& req,
                                 httplib::Response& res) {
      try {
        json request_json = json::parse(req.body);

        json response_json = handler(request_json);

        res.set_content(response_json.dump(), "application/json");
      } catch (const std::exception& e) {
        res.status = 400;
        res.set_content(json({{"error", e.what()}}).dump(), "application/json");
      }
    });
  }

  void start() {
    std::cout << "Server starting at http://" << host_ << ":" << port_ << '\n';
    if (!server_.listen(host_, port_)) {
      std::cerr << "Server failed to start!" << '\n';
    }
  }

  void stop() { server_.stop(); }

 private:
  httplib::Server server_;
  std::string host_;
  int port_;
};
