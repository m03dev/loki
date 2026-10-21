/*
    serializer.cpp: Helper class to serialize the application state to a .PLY file

    This file is part of the implementation of

        Instant Field-Aligned Meshes
        Wenzel Jakob, Daniele Panozzo, Marco Tarini, and Olga Sorkine-Hornung
        In ACM Transactions on Graphics (Proc. SIGGRAPH Asia 2015)

    All rights reserved. Use of this source code is governed by a
    BSD-style license that can be found in the LICENSE.txt file.
*/

// Sculpting engine: file I/O (PLY via rply) removed - Sculpting never saves Instant Meshes
// state. The file-based entry points throw if ever called.
#include "serializer.h"
#include <set>
#include <stdexcept>

Serializer::Serializer() : mCompatibilityMode(false) { mPrefixStack.push(""); }

bool Serializer::isSerializedFile(const std::string &) { return false; }

Serializer::Serializer(const std::string &, bool compatibilityMode, const ProgressCallback &)
    : mCompatibilityMode(compatibilityMode) {
    throw std::runtime_error("Serializer: file loading is not available in this build");
}

void Serializer::write(const std::string &, const ProgressCallback &) {
    throw std::runtime_error("Serializer: file writing is not available in this build");
}

std::vector<std::string> Serializer::getKeys() const {
    const std::string &prefix = mPrefixStack.top();
    std::vector<std::string> result;
    for (auto const &kv : mData) {
        if (kv.first.substr(0, prefix.length()) == prefix)
            result.push_back(kv.first.substr(prefix.length()));
    }
    return result;
}

Serializer::~Serializer() {
    #define IMPLEMENT(type) \
        case Variant::Type::List_##type: delete kv.second.list_##type; break; \
        case Variant::Type::Matrix_##type: delete kv.second.matrix_##type; break;

    for (auto const &kv : mData) {
        switch (kv.second.type_id) {
            IMPLEMENT(uint8_t);
            IMPLEMENT(uint16_t);
            IMPLEMENT(uint32_t);
            IMPLEMENT(float);
            IMPLEMENT(double);
            default: break;
        }
    }

    #undef IMPLEMENT
}

size_t Serializer::totalSize() const {
    size_t result = 0;

    #define IMPLEMENT(type) \
        case Variant::Type::Matrix_##type: \
            result += kv.second.matrix_##type->size() * sizeof(type); \
            break; \
        case Variant::Type::List_##type: {\
                const std::vector<std::vector<type>> &list = *kv.second.list_##type; \
                for (uint32_t i=0; i<list.size(); ++i) \
                    result += list[i].size() * sizeof(type) + sizeof(uint32_t); \
            } \
            break;

    for (auto const &kv : mData) {
        switch (kv.second.type_id) {
            IMPLEMENT(uint8_t);
            IMPLEMENT(uint16_t);
            IMPLEMENT(uint32_t);
            IMPLEMENT(float);
            IMPLEMENT(double);
        }
    }

    #undef IMPLEMENT
    return result;
}

bool Serializer::diff(const Serializer &other) const {
    std::set<std::string> keys;
    for (auto const &kv : mData)
        keys.insert(kv.first);
    for (auto const &kv : other.mData)
        keys.insert(kv.first);

    bool diff = false;

    for (const std::string &key : keys) {
        auto it1 = mData.find(key);
        if (it1 == mData.end()) {
            cout << "Element " << key << " does not exist in serializer 1." << endl;
            diff = true;
            continue;
        }
        auto it2 = other.mData.find(key);
        if (it2 == other.mData.end()) {
            cout << "Element " << key << " does not exist in serializer 2." << endl;
            diff = true;
            continue;
        }
        const Variant &v1 = it1->second;
        const Variant &v2 = it2->second;
        if (v1.type_id != v2.type_id) {
            cout << "Element " << key << " have different types." << endl;
            diff = true;
            continue;
        }

        #define IMPLEMENT(type) \
            case Variant::Type::Matrix_##type: \
                if (v1.matrix_##type->cols() != v2.matrix_##type->cols() || \
                    v1.matrix_##type->rows() != v2.matrix_##type->rows()) \
                    result = true; \
                else \
                    result = *(v1.matrix_##type) != *(v2.matrix_##type); \
                break; \
            case Variant::Type::List_##type: \
                result = *(v1.list_##type) != *(v2.list_##type); \
                break;

        bool result = false;
        switch (v1.type_id) {
            IMPLEMENT(uint8_t);
            IMPLEMENT(uint16_t);
            IMPLEMENT(uint32_t);
            IMPLEMENT(float);
            IMPLEMENT(double);
            default:
                throw std::runtime_error("Unexpected data type while diffing!");
                break;
        }

        #undef IMPLEMENT

        if (result) {
            cout << "Element " << key << " differs." << endl;
            diff = true;
        }
    }

    return diff;
}

std::ostream &operator<<(std::ostream &os, const Serializer &state) {
    os << "Serializer[";
    bool first = true;
    for (auto const &kv : state.mData) {
        const Serializer::Variant &v = kv.second;
        if (!first)
            cout << ",";
        first = false;
        cout << endl;
        std::string tname, value;

        #define IMPLEMENT(type) \
            case Serializer::Variant::Type::Matrix_##type: { \
                    const Eigen::Matrix<type, Eigen::Dynamic, Eigen::Dynamic> &mat = *(v.matrix_##type); \
                    if (mat.size() == 1) { \
                        tname = #type; \
                        value = std::to_string(mat(0, 0)); \
                    } else if (mat.cols() == 1 && mat.rows() <= 4) { \
                        tname = "vec<" #type ">"; \
                        value = "["; \
                        for (int i=0; i<mat.rows(); ++i) { \
                            value += std::to_string(mat(i, 0)); \
                            if (i+1<mat.rows()) \
                                value += ", "; \
                        } \
                        value += "]"; \
                    } else { \
                        tname = std::string(mat.cols() == 1 ? "vec<" : "mat<") + #type + std::string(">"); \
                        value = "data[" + std::to_string(mat.rows()) + "x" + \
                                          std::to_string(mat.cols()) + "]"; \
                    } \
                } \
                break; \
            case Serializer::Variant::Type::List_##type: \
                tname = #type "**"; \
                value = "data[" + std::to_string(v.list_##type->size()) + "][]"; \
                break; \

        switch (v.type_id) {
            IMPLEMENT(uint8_t);
            IMPLEMENT(uint16_t);
            IMPLEMENT(uint32_t);
            IMPLEMENT(float);
            IMPLEMENT(double);
            default:
                throw std::runtime_error("Unexpected type in stream operator");
        }
        os << "\t" << tname << " " << kv.first << " = " << value;
    }
    os << endl << "]";
    return os;
}
