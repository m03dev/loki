// LOKI's Babylon.js build: only what LOKI World and LOKI's games use.
import { Engine } from "core/Engines/engine";
import { Scene } from "core/scene";
import { ArcRotateCamera } from "core/Cameras/arcRotateCamera";
import { FreeCamera } from "core/Cameras/freeCamera";
import { HemisphericLight } from "core/Lights/hemisphericLight";
import { DirectionalLight } from "core/Lights/directionalLight";
import { PointLight } from "core/Lights/pointLight";
import { ShadowGenerator } from "core/Lights/Shadows/shadowGenerator";
import "core/Lights/Shadows/shadowGeneratorSceneComponent";
import { Vector3, Matrix, Quaternion } from "core/Maths/math.vector";
import { Color3, Color4 } from "core/Maths/math.color";
import { MeshBuilder } from "core/Meshes/meshBuilder";
import { Mesh } from "core/Meshes/mesh";
import { TransformNode } from "core/Meshes/transformNode";
import { VertexData } from "core/Meshes/mesh.vertexData";
import "core/Meshes/thinInstanceMesh";
import "core/Meshes/instancedMesh";
import { StandardMaterial } from "core/Materials/standardMaterial";
import { ShaderMaterial } from "core/Materials/shaderMaterial";
import { Effect } from "core/Materials/effect";
import { Texture } from "core/Materials/Textures/texture";
import { DynamicTexture } from "core/Materials/Textures/dynamicTexture";
import { PostProcess } from "core/PostProcesses/postProcess";
import { ParticleSystem } from "core/Particles/particleSystem";
import "core/Rendering/outlineRenderer";
import "core/Rendering/edgesRenderer";
import { Animation } from "core/Animations/animation";
import "core/Animations/animatable";
import { Ray } from "core/Culling/ray";
import "core/Culling/ray";
import { PointerEventTypes } from "core/Events/pointerEvents";
import { KeyboardEventTypes } from "core/Events/keyboardEvents";
import { CellMaterial } from "materials/cell/cellMaterial";
import { Material } from "core/Materials/material";
import { Constants } from "core/Engines/constants";
import { Vector2, Vector4 } from "core/Maths/math.vector";
(window as any).BABYLON = { Engine, Scene, ArcRotateCamera, FreeCamera, HemisphericLight, DirectionalLight, PointLight,
  ShadowGenerator, Vector3, Matrix, Quaternion, Color3, Color4, MeshBuilder, Mesh, TransformNode, VertexData,
  StandardMaterial, ShaderMaterial, Effect, Texture, DynamicTexture, PostProcess, ParticleSystem, Animation, Ray,
  PointerEventTypes, KeyboardEventTypes, CellMaterial, Material, Constants, Vector2, Vector4 };
