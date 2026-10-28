#pragma once
#include "Arduino.h"
class WebServer {
public:
 std::map<std::string,String> args;
 String clientHeader="1",body;int response=0;
 WebServer(int){}bool hasArg(const char *s){return args.count(s);}String arg(const char *s){return args[s];}String header(const char*){return clientHeader;}
 void send(int code,const char*,String text){response=code;body=text;}
 void sendHeader(const char*,const char*){}void send_P(int,const char*,const char*){}
 template<class F>void on(const char*,int,F){}template<class F>void onNotFound(F){}
 void collectHeaders(const char**,int){}void begin(){}void handleClient(){}
};
