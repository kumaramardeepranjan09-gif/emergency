#pragma once
#include <algorithm>
#include <cstdint>
#include <cmath>
#include <cstring>
#include <string>
#include <sstream>
#include <iomanip>
#include <map>
#include <vector>
#include <deque>
#include <cctype>
using std::min;using std::max;
using byte=uint8_t;
#define PROGMEM
#define HIGH 1
#define LOW 0
#define OUTPUT 1
#define WIFI_AP 2
#define HTTP_GET 0
#define HTTP_POST 1
inline uint32_t fakeMillis=10000;
inline std::map<int,int> digitalPins,pwmPins;
inline uint32_t millis(){return fakeMillis;}
inline void delay(uint32_t n){fakeMillis+=n;}
inline void pinMode(int,int){}
inline void digitalWrite(int pin,int value){digitalPins[pin]=value;}
inline void analogWrite(int pin,int value){pwmPins[pin]=value;}
template<class T>T constrain(T v,T low,T hi){return std::min(std::max(v,low),hi);}
class String {
public:
 std::string s;
 String()=default;String(const char *v):s(v?v:""){}String(std::string v):s(v){}String(char c):s(1,c){}
 template<class T,typename std::enable_if<std::is_integral<T>::value,int>::type=0>String(T v):s(std::to_string(v)){}
 String(double v,int digits=2){std::ostringstream o;o<<std::fixed<<std::setprecision(digits)<<v;s=o.str();}
 size_t length()const{return s.size();}void reserve(size_t n){s.reserve(n);}char operator[](size_t n)const{return s[n];}
 const char *c_str()const{return s.c_str();}void toUpperCase(){for(char &c:s)c=std::toupper((unsigned char)c);}
 long toInt()const{try{return std::stol(s);}catch(...){return 0;}}
 bool startsWith(const char *v)const{return s.rfind(v,0)==0;}
 bool endsWith(const char *v)const{std::string t(v);return s.size()>=t.size()&&s.compare(s.size()-t.size(),t.size(),t)==0;}
 int indexOf(char c)const{auto p=s.find(c);return p==std::string::npos?-1:(int)p;}
 String &operator+=(const String &v){s+=v.s;return *this;}
 friend String operator+(const String&a,const String&b){return String(a.s+b.s);}
 friend bool operator==(const String&a,const String&b){return a.s==b.s;}
 friend bool operator!=(const String&a,const String&b){return !(a==b);}
};
struct SerialFake {void begin(int){}template<class T>void print(T){}template<class T>void println(T){}};
inline SerialFake Serial;
