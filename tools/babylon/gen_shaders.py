import os, re, sys
TEMPLATE = """// Do not edit.
import { ShaderStore } from "##LOC##";
##INC##
const name = "##NAME##";
const shader = `##SHADER##`;
// Sideeffect
if (!ShaderStore.##STORE##[name]) {
    ShaderStore.##STORE##[name] = shader;
}
/** @internal */
export const ##EXPORT## = { name, shader };
"""
def shader_name(fn):
    p = fn.split(".")
    if p[1] != "fx":
        return p[0] + ("Pixel" if p[1] == "fragment" else "Compute" if p[1] == "compute" else "Vertex") + "Shader"
    return p[0]
def includes(src):
    out = []
    for m in re.finditer(r"#include<(.+?)>(\((.*?)\))*(\[(.*?)\])*", src):
        f = m.group(1)
        if "__decl__" in f:
            f = f.replace("__decl__", "")
            for x in (f + "Declaration", f.replace("Vertex", "Ubo").replace("Fragment", "Ubo") + "Declaration"):
                if x not in out: out.append(x)
        elif f not in out:
            out.append(f)
    return out
def build(path, is_core):
    src = open(path, encoding="utf-8").read()
    fn = os.path.basename(path); d = os.path.dirname(path)
    wgsl = "WGSL" in d
    s = src.replace("﻿", "").replace("\r\n", "\n")
    s = re.sub(r"(//)+.*$", "", s, flags=re.M)
    s = re.sub(r"\t+", " ", s, flags=re.M)
    s = re.sub(r"^\s+", "", s, flags=re.M)
    s = re.sub(r" ([\*/=\+\-><]+) ", r"\1", s)
    s = re.sub(r",[ ]", ",", s)
    s = re.sub(r" {1,}", " ", s)
    s = re.sub(r"^#(.*)", r"#\1\n", s, flags=re.M)
    s = re.sub(r"\{\n([^#])", r"{\1", s)
    s = s.replace("\n}", "}")
    s = re.sub(r"^(?:[\t ]*(?:\r?\n|\r))+", "", s, flags=re.M)
    s = re.sub(r";\n([^#])", r";\1", s)
    s = s.replace("`", "\\`")
    is_inc = "ShadersInclude" in d
    inc = ""
    for e in includes(src):
        inc += ('import "./%s";\n' % e) if (is_core and is_inc) else ('import "./ShadersInclude/%s";\n' % e) if is_core else ('import "core/Shaders%s/ShadersInclude/%s";\n' % ("WGSL" if wgsl else "", e))
    store = ("IncludesShadersStore" if is_inc else "ShadersStore") + ("WGSL" if wgsl else "")
    loc = ("../../Engines/shaderStore" if is_inc else "../Engines/shaderStore") if is_core else "core/Engines/shaderStore"
    name = shader_name(fn)
    ts = TEMPLATE.replace("##LOC##", loc).replace("##INC##", inc).replace("##NAME##", name).replace("##SHADER##", s).replace("##STORE##", store).replace("##EXPORT##", name + ("WGSL" if wgsl else ""))
    out = os.path.join(d, fn.replace(".fx", ".ts").replace(".wgsl", ".ts"))
    open(out, "w", encoding="utf-8").write(ts)
n = 0
for root, is_core in ((sys.argv[1], True), (sys.argv[2], False)):
    for dp, dn, fns in os.walk(root):
        for f in fns:
            if f.endswith(".fx") or f.endswith(".wgsl"):
                build(os.path.join(dp, f), is_core); n += 1
print("generated", n)
