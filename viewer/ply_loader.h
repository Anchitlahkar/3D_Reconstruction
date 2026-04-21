#pragma once

#include <string>
#include <vector>

struct Point {
    float x;
    float y;
    float z;
    unsigned char r;
    unsigned char g;
    unsigned char b;
};

std::vector<Point> LoadPLY(const std::string& path);
