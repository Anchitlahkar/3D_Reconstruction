#include "ply_loader.h"

#include <algorithm>
#include <array>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

enum class PlyFormat {
    kUnknown,
    kAscii,
    kBinaryLittleEndian,
};

struct PropertyInfo {
    std::string type;
    std::string name;
    int size = 0;
};

struct VertexLayout {
    int xIndex = -1;
    int yIndex = -1;
    int zIndex = -1;
    int nxIndex = -1;
    int nyIndex = -1;
    int nzIndex = -1;
    int rIndex = -1;
    int gIndex = -1;
    int bIndex = -1;
};

struct PlyHeader {
    PlyFormat format = PlyFormat::kUnknown;
    std::size_t vertexCount = 0;
    std::vector<PropertyInfo> vertexProperties;
};

std::string ToLower(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char ch) {
        return static_cast<char>(std::tolower(ch));
    });
    return value;
}

void TrimTrailingCarriageReturn(std::string& value) {
    if (!value.empty() && value.back() == '\r') {
        value.pop_back();
    }
}

int PropertySize(const std::string& type) {
    if (type == "char" || type == "uchar" || type == "int8" || type == "uint8") {
        return 1;
    }
    if (type == "short" || type == "ushort" || type == "int16" || type == "uint16") {
        return 2;
    }
    if (type == "int" || type == "uint" || type == "float" || type == "int32" || type == "uint32" || type == "float32") {
        return 4;
    }
    if (type == "double" || type == "float64" || type == "int64" || type == "uint64") {
        return 8;
    }
    throw std::runtime_error("Unsupported PLY property type: " + type);
}

std::string FormatToString(PlyFormat format) {
    switch (format) {
    case PlyFormat::kAscii:
        return "ascii";
    case PlyFormat::kBinaryLittleEndian:
        return "binary_little_endian";
    default:
        return "unknown";
    }
}

int FindPropertyIndex(const std::vector<PropertyInfo>& properties, const std::initializer_list<std::string>& names) {
    for (const std::string& candidate : names) {
        for (int index = 0; index < static_cast<int>(properties.size()); ++index) {
            if (properties[static_cast<std::size_t>(index)].name == candidate) {
                return index;
            }
        }
    }
    return -1;
}

VertexLayout BuildVertexLayout(const std::vector<PropertyInfo>& properties) {
    VertexLayout layout = {};
    layout.xIndex = FindPropertyIndex(properties, {"x"});
    layout.yIndex = FindPropertyIndex(properties, {"y"});
    layout.zIndex = FindPropertyIndex(properties, {"z"});
    layout.nxIndex = FindPropertyIndex(properties, {"nx", "normal_x"});
    layout.nyIndex = FindPropertyIndex(properties, {"ny", "normal_y"});
    layout.nzIndex = FindPropertyIndex(properties, {"nz", "normal_z"});
    layout.rIndex = FindPropertyIndex(properties, {"red", "r", "diffuse_red"});
    layout.gIndex = FindPropertyIndex(properties, {"green", "g", "diffuse_green"});
    layout.bIndex = FindPropertyIndex(properties, {"blue", "b", "diffuse_blue"});
    return layout;
}

unsigned char ClampColor(double value) {
    value = std::clamp(value, 0.0, 255.0);
    return static_cast<unsigned char>(std::lround(value));
}

template <typename T>
T ReadLittleEndian(std::ifstream& file) {
    std::array<unsigned char, sizeof(T)> bytes = {};
    file.read(reinterpret_cast<char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
    if (!file) {
        throw std::runtime_error("Unexpected end of file while reading binary PLY data.");
    }

    T value{};
    unsigned char* out = reinterpret_cast<unsigned char*>(&value);
    for (std::size_t i = 0; i < bytes.size(); ++i) {
        out[i] = bytes[i];
    }
    return value;
}

double ReadBinaryScalar(std::ifstream& file, const std::string& type) {
    if (type == "char" || type == "int8") return static_cast<double>(ReadLittleEndian<std::int8_t>(file));
    if (type == "uchar" || type == "uint8") return static_cast<double>(ReadLittleEndian<std::uint8_t>(file));
    if (type == "short" || type == "int16") return static_cast<double>(ReadLittleEndian<std::int16_t>(file));
    if (type == "ushort" || type == "uint16") return static_cast<double>(ReadLittleEndian<std::uint16_t>(file));
    if (type == "int" || type == "int32") return static_cast<double>(ReadLittleEndian<std::int32_t>(file));
    if (type == "uint" || type == "uint32") return static_cast<double>(ReadLittleEndian<std::uint32_t>(file));
    if (type == "int64") return static_cast<double>(ReadLittleEndian<std::int64_t>(file));
    if (type == "uint64") return static_cast<double>(ReadLittleEndian<std::uint64_t>(file));
    if (type == "float" || type == "float32") return static_cast<double>(ReadLittleEndian<float>(file));
    if (type == "double" || type == "float64") return ReadLittleEndian<double>(file);
    throw std::runtime_error("Unsupported binary PLY property type: " + type);
}

Point MapPoint(const std::vector<double>& values, const VertexLayout& layout) {
    Point point = {};
    point.x = static_cast<float>(values[static_cast<std::size_t>(layout.xIndex)]);
    point.y = static_cast<float>(values[static_cast<std::size_t>(layout.yIndex)]);
    point.z = static_cast<float>(values[static_cast<std::size_t>(layout.zIndex)]);
    point.r = layout.rIndex >= 0 ? ClampColor(values[static_cast<std::size_t>(layout.rIndex)]) : 255;
    point.g = layout.gIndex >= 0 ? ClampColor(values[static_cast<std::size_t>(layout.gIndex)]) : 255;
    point.b = layout.bIndex >= 0 ? ClampColor(values[static_cast<std::size_t>(layout.bIndex)]) : 255;
    return point;
}

void ValidatePoint(const Point& point, std::size_t index) {
    const auto validCoordinate = [](float value) {
        return std::isfinite(value) && value >= -10000.0f && value <= 10000.0f;
    };

    if (!validCoordinate(point.x) || !validCoordinate(point.y) || !validCoordinate(point.z)) {
        std::ostringstream message;
        message << "PLY format mismatch - check property layout. "
                << "Invalid point at vertex " << index
                << ": (" << point.x << ", " << point.y << ", " << point.z << ")";
        throw std::runtime_error(message.str());
    }
}

void ValidateEarlyPoints(const std::vector<Point>& points) {
    const std::size_t sampleCount = std::min<std::size_t>(5, points.size());
    for (std::size_t index = 0; index < sampleCount; ++index) {
        ValidatePoint(points[index], index);
    }
}

void PrintDebugSummary(const PlyHeader& header) {
    std::cout << "PLY Loaded:\n";
    std::cout << "format: " << FormatToString(header.format) << '\n';
    std::cout << "vertices: " << header.vertexCount << '\n';
    std::cout << "properties:";
    for (const PropertyInfo& property : header.vertexProperties) {
        std::cout << ' ' << property.name;
    }
    std::cout << '\n';
}

PlyHeader ParseHeader(std::ifstream& file, const std::string& path) {
    PlyHeader headerInfo = {};
    bool insideVertexElement = false;
    bool sawEndHeader = false;

    std::string line;
    if (!std::getline(file, line)) {
        throw std::runtime_error("Empty PLY file: " + path);
    }
    TrimTrailingCarriageReturn(line);
    if (line != "ply") {
        throw std::runtime_error("Input is not a PLY file: " + path);
    }

    while (std::getline(file, line)) {
        TrimTrailingCarriageReturn(line);
        if (line == "end_header") {
            sawEndHeader = true;
            break;
        }
        if (line.empty()) {
            continue;
        }

        std::istringstream headerLine(line);
        std::string token;
        headerLine >> token;
        token = ToLower(token);

        if (token == "comment" || token == "obj_info") {
            continue;
        }

        if (token == "format") {
            std::string formatName;
            std::string version;
            headerLine >> formatName >> version;
            formatName = ToLower(formatName);
            if (formatName == "ascii") {
                headerInfo.format = PlyFormat::kAscii;
            } else if (formatName == "binary_little_endian") {
                headerInfo.format = PlyFormat::kBinaryLittleEndian;
            } else {
                throw std::runtime_error("Only ASCII and binary_little_endian PLY files are supported.");
            }
            continue;
        }

        if (token == "element") {
            std::string elementName;
            std::size_t count = 0;
            headerLine >> elementName >> count;
            elementName = ToLower(elementName);
            insideVertexElement = elementName == "vertex";
            if (insideVertexElement) {
                headerInfo.vertexCount = count;
                headerInfo.vertexProperties.clear();
            }
            continue;
        }

        if (token == "property" && insideVertexElement) {
            std::string type;
            headerLine >> type;
            type = ToLower(type);

            if (type == "list") {
                throw std::runtime_error("PLY vertex list properties are not supported.");
            }

            std::string name;
            headerLine >> name;
            name = ToLower(name);
            if (name.empty()) {
                throw std::runtime_error("Malformed PLY property definition.");
            }

            headerInfo.vertexProperties.push_back({type, name, PropertySize(type)});
        }
    }

    if (!sawEndHeader) {
        throw std::runtime_error("PLY header is missing end_header.");
    }

    if (headerInfo.vertexCount == 0) {
        throw std::runtime_error("PLY file does not define any vertices.");
    }

    if (headerInfo.vertexProperties.empty()) {
        throw std::runtime_error("PLY vertex element does not define any scalar properties.");
    }

    return headerInfo;
}

std::vector<Point> LoadAsciiVertices(
    std::ifstream& file,
    const PlyHeader& header,
    const VertexLayout& layout
) {
    std::vector<Point> points;
    points.reserve(header.vertexCount);

    std::vector<double> values(header.vertexProperties.size(), 0.0);
    std::string line;
    while (points.size() < header.vertexCount && std::getline(file, line)) {
        TrimTrailingCarriageReturn(line);
        if (line.empty()) {
            continue;
        }

        std::istringstream row(line);
        for (std::size_t propertyIndex = 0; propertyIndex < header.vertexProperties.size(); ++propertyIndex) {
            if (!(row >> values[propertyIndex])) {
                throw std::runtime_error("Failed to parse ASCII PLY vertex row.");
            }
        }

        points.push_back(MapPoint(values, layout));
        if (points.size() <= 5) {
            ValidatePoint(points.back(), points.size() - 1);
        }
    }

    if (points.size() != header.vertexCount) {
        throw std::runtime_error("PLY vertex count does not match ASCII payload.");
    }

    return points;
}

std::vector<Point> LoadBinaryVertices(
    std::ifstream& file,
    const PlyHeader& header,
    const VertexLayout& layout
) {
    std::vector<Point> points;
    points.reserve(header.vertexCount);

    std::vector<double> values(header.vertexProperties.size(), 0.0);
    for (std::size_t vertexIndex = 0; vertexIndex < header.vertexCount; ++vertexIndex) {
        for (std::size_t propertyIndex = 0; propertyIndex < header.vertexProperties.size(); ++propertyIndex) {
            values[propertyIndex] = ReadBinaryScalar(file, header.vertexProperties[propertyIndex].type);
        }

        points.push_back(MapPoint(values, layout));
        if (points.size() <= 5) {
            ValidatePoint(points.back(), points.size() - 1);
        }
    }

    return points;
}

}  // namespace

std::vector<Point> LoadPLY(const std::string& path) {
    std::ifstream file(path, std::ios::binary);
    if (!file) {
        throw std::runtime_error("Could not open PLY file: " + path);
    }

    std::array<char, 1 << 16> readBuffer = {};
    file.rdbuf()->pubsetbuf(readBuffer.data(), static_cast<std::streamsize>(readBuffer.size()));

    const PlyHeader header = ParseHeader(file, path);
    const VertexLayout layout = BuildVertexLayout(header.vertexProperties);

    if (layout.xIndex < 0 || layout.yIndex < 0 || layout.zIndex < 0) {
        throw std::runtime_error("PLY vertex data must include x, y, and z properties.");
    }

    PrintDebugSummary(header);

    std::vector<Point> points = header.format == PlyFormat::kAscii
        ? LoadAsciiVertices(file, header, layout)
        : LoadBinaryVertices(file, header, layout);

    if (points.empty()) {
        throw std::runtime_error("PLY file did not yield any readable points.");
    }

    ValidateEarlyPoints(points);
    return points;
}
