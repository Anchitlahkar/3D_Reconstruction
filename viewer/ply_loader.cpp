#include "ply_loader.h"

#include <algorithm>
#include <array>
#include <cctype>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

struct PropertyInfo {
    std::string type;
    std::string name;
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

int FindPropertyIndex(const std::vector<PropertyInfo>& properties, const std::string& name) {
    for (int index = 0; index < static_cast<int>(properties.size()); ++index) {
        if (properties[index].name == name) {
            return index;
        }
    }
    return -1;
}

unsigned char ClampColor(double value) {
    value = std::clamp(value, 0.0, 255.0);
    return static_cast<unsigned char>(value);
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

double ReadBinaryValue(std::ifstream& file, const std::string& type) {
    std::array<unsigned char, 8> bytes = {};
    const int byteCount = PropertySize(type);
    file.read(reinterpret_cast<char*>(bytes.data()), byteCount);
    if (!file) {
        throw std::runtime_error("Unexpected end of file while reading binary PLY data.");
    }

    if (type == "float" || type == "float32") {
        std::uint32_t raw = 0;
        for (int i = 0; i < 4; ++i) {
            raw |= static_cast<std::uint32_t>(bytes[static_cast<std::size_t>(i)]) << (8 * i);
        }
        float value = 0.0f;
        std::memcpy(&value, &raw, sizeof(value));
        return value;
    }

    if (type == "double" || type == "float64") {
        std::uint64_t raw = 0;
        for (int i = 0; i < 8; ++i) {
            raw |= static_cast<std::uint64_t>(bytes[static_cast<std::size_t>(i)]) << (8 * i);
        }
        double value = 0.0;
        std::memcpy(&value, &raw, sizeof(value));
        return value;
    }

    auto readUnsigned = [&](int bits) -> std::uint64_t {
        std::uint64_t raw = 0;
        for (int i = 0; i < bits / 8; ++i) {
            raw |= static_cast<std::uint64_t>(bytes[static_cast<std::size_t>(i)]) << (8 * i);
        }
        return raw;
    };

    if (type == "uchar" || type == "uint8") return static_cast<double>(bytes[0]);
    if (type == "char" || type == "int8") return static_cast<double>(static_cast<std::int8_t>(bytes[0]));
    if (type == "ushort" || type == "uint16") return static_cast<double>(readUnsigned(16));
    if (type == "short" || type == "int16") return static_cast<double>(static_cast<std::int16_t>(readUnsigned(16)));
    if (type == "uint" || type == "uint32") return static_cast<double>(readUnsigned(32));
    if (type == "int" || type == "int32") return static_cast<double>(static_cast<std::int32_t>(readUnsigned(32)));
    if (type == "uint64") return static_cast<double>(readUnsigned(64));
    if (type == "int64") return static_cast<double>(static_cast<std::int64_t>(readUnsigned(64)));

    throw std::runtime_error("Unsupported binary PLY property type: " + type);
}

std::vector<Point> LoadAsciiVertices(
    std::ifstream& file,
    int vertexCount,
    const std::vector<PropertyInfo>& properties,
    int xIndex,
    int yIndex,
    int zIndex,
    int rIndex,
    int gIndex,
    int bIndex
) {
    std::vector<Point> points;
    points.reserve(static_cast<std::size_t>(vertexCount));

    std::vector<double> values(properties.size(), 0.0);
    std::string line;
    while (static_cast<int>(points.size()) < vertexCount && std::getline(file, line)) {
        TrimTrailingCarriageReturn(line);
        if (line.empty()) {
            continue;
        }

        std::istringstream row(line);
        for (double& value : values) {
            if (!(row >> value)) {
                throw std::runtime_error("Failed to parse ASCII PLY vertex row.");
            }
        }

        Point point = {};
        point.x = static_cast<float>(values[static_cast<std::size_t>(xIndex)]);
        point.y = static_cast<float>(values[static_cast<std::size_t>(yIndex)]);
        point.z = static_cast<float>(values[static_cast<std::size_t>(zIndex)]);
        point.r = rIndex >= 0 ? ClampColor(values[static_cast<std::size_t>(rIndex)]) : 255;
        point.g = gIndex >= 0 ? ClampColor(values[static_cast<std::size_t>(gIndex)]) : 255;
        point.b = bIndex >= 0 ? ClampColor(values[static_cast<std::size_t>(bIndex)]) : 255;
        points.push_back(point);
    }

    return points;
}

std::vector<Point> LoadBinaryVertices(
    std::ifstream& file,
    int vertexCount,
    const std::vector<PropertyInfo>& properties,
    int xIndex,
    int yIndex,
    int zIndex,
    int rIndex,
    int gIndex,
    int bIndex
) {
    std::vector<Point> points;
    points.reserve(static_cast<std::size_t>(vertexCount));

    std::vector<double> values(properties.size(), 0.0);
    for (int vertex = 0; vertex < vertexCount; ++vertex) {
        for (int property = 0; property < static_cast<int>(properties.size()); ++property) {
            values[static_cast<std::size_t>(property)] = ReadBinaryValue(file, properties[static_cast<std::size_t>(property)].type);
        }

        Point point = {};
        point.x = static_cast<float>(values[static_cast<std::size_t>(xIndex)]);
        point.y = static_cast<float>(values[static_cast<std::size_t>(yIndex)]);
        point.z = static_cast<float>(values[static_cast<std::size_t>(zIndex)]);
        point.r = rIndex >= 0 ? ClampColor(values[static_cast<std::size_t>(rIndex)]) : 255;
        point.g = gIndex >= 0 ? ClampColor(values[static_cast<std::size_t>(gIndex)]) : 255;
        point.b = bIndex >= 0 ? ClampColor(values[static_cast<std::size_t>(bIndex)]) : 255;
        points.push_back(point);
    }

    return points;
}

}  // namespace

std::vector<Point> LoadPLY(const std::string& path) {
    std::ifstream file(path, std::ios::binary);
    if (!file) {
        throw std::runtime_error("Could not open PLY file: " + path);
    }

    std::string line;
    std::getline(file, line);
    TrimTrailingCarriageReturn(line);
    if (line != "ply") {
        throw std::runtime_error("Input is not a PLY file: " + path);
    }

    bool asciiFormat = false;
    bool binaryLittleEndian = false;
    int vertexCount = 0;
    bool readingVertexProperties = false;
    std::vector<PropertyInfo> properties;

    while (std::getline(file, line)) {
        TrimTrailingCarriageReturn(line);
        if (line == "end_header") {
            break;
        }

        std::istringstream header(line);
        std::string token;
        header >> token;
        token = ToLower(token);

        if (token == "format") {
            std::string format;
            header >> format;
            format = ToLower(format);
            asciiFormat = format == "ascii";
            binaryLittleEndian = format == "binary_little_endian";
        } else if (token == "element") {
            std::string elementName;
            header >> elementName;
            elementName = ToLower(elementName);
            readingVertexProperties = elementName == "vertex";
            if (readingVertexProperties) {
                header >> vertexCount;
                properties.clear();
            }
        } else if (token == "property" && readingVertexProperties) {
            std::string type;
            header >> type;
            type = ToLower(type);

            if (type == "list") {
                std::string countType;
                std::string itemType;
                std::string name;
                header >> countType >> itemType >> name;
                continue;
            }

            std::string name;
            header >> name;
            properties.push_back({type, ToLower(name)});
        }
    }

    if (!asciiFormat && !binaryLittleEndian) {
        throw std::runtime_error("Only ASCII and binary_little_endian PLY files are supported.");
    }
    if (vertexCount <= 0) {
        throw std::runtime_error("PLY file does not define any vertices.");
    }

    const int xIndex = FindPropertyIndex(properties, "x");
    const int yIndex = FindPropertyIndex(properties, "y");
    const int zIndex = FindPropertyIndex(properties, "z");
    if (xIndex < 0 || yIndex < 0 || zIndex < 0) {
        throw std::runtime_error("PLY vertex data must include x, y, and z properties.");
    }

    int rIndex = FindPropertyIndex(properties, "red");
    int gIndex = FindPropertyIndex(properties, "green");
    int bIndex = FindPropertyIndex(properties, "blue");
    if (rIndex < 0) rIndex = FindPropertyIndex(properties, "r");
    if (gIndex < 0) gIndex = FindPropertyIndex(properties, "g");
    if (bIndex < 0) bIndex = FindPropertyIndex(properties, "b");

    std::vector<Point> points = asciiFormat
        ? LoadAsciiVertices(file, vertexCount, properties, xIndex, yIndex, zIndex, rIndex, gIndex, bIndex)
        : LoadBinaryVertices(file, vertexCount, properties, xIndex, yIndex, zIndex, rIndex, gIndex, bIndex);

    if (points.empty()) {
        throw std::runtime_error("PLY file did not yield any readable points.");
    }

    return points;
}
