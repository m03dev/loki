# Forge = Maya 2027 - the plan and the record

Owner 2026-10-22: "rework everything so its like that, its almost 1:1 to maya ... place everything exactly like
that, thats how maya works and those are where those functions go".

The `bk_maya` folder the owner pointed to turned out to be BlendKit's asset-library plug-in for Maya (an asset
bar + drag-and-drop placement, GPL-3.0) - it holds no Maya layout. The layout comes from **Maya 2027 itself**,
read from the owner's install by `tools/forge_maya/extract_maya.py` into `docs/forge/maya2027_layout.json` (names,
order, compass positions and keys only - no Autodesk code). `tools/forge_maya/gen_layout.py` turns it into
`app/ui/forge_maya_layout.js`, which Forge's menus, hotbox and marking menus are built from, and writes this file.

## The plan

1. **Menu bar and menu sets** (done): File Edit Create Select Modify Display Windows, then the set's menus - Modeling
   (F2): Mesh, Edit Mesh, Mesh Tools, Mesh Display, UV (Curves, Surfaces, Deform, Generate when Forge has rows
   for them); Animation (F4): Key, Playback; Rendering (F6): Render; Sculpting (Forge's own). Snap and Symmetry
   live on the status line, as in Maya.
2. **Every menu in Maya's order, with Maya's labels and section headings** (done for every row Forge can run; Forge's
   own extras sit under a *LOKI* heading at the end of the menu they belong with).
3. **Marking menus at Maya's compass positions** (done): Shift+right-click on an object / vertex / edge / face / empty
   space (contextPolyTools*MM); the hotbox's centre, north, south, east and west zones (Hotbox*Menu).
4. **Hotkeys = Maya's defaults** (done for the keys Forge has; see *Hotkeys* below).
5. **Build the missing commands, most-used first** (next): every "not yet" row below is a command to write.
   Order: Edit Mesh and Mesh Tools rows, then Mesh, Mesh Display, Select conversions, Modify (Match / Snap Align),
   File (New / Open / Save As / Import), UV, Key / Playback.
6. **Panel menus** (View Shading Lighting Show Renderer Panels) laid out from Maya's panel scripts (next).

## Where Forge stands

284 of 1113 Maya rows in the menus, hotbox and marking menus are in Forge (26%).

| Menu | In Forge | Maya rows |
| --- | ---: | ---: |
| File | 6 | 24 |
| Edit | 14 | 57 |
| Create | 8 | 66 |
| Select | 30 | 79 |
| Modify | 9 | 95 |
| Display | 10 | 121 |
| Windows | 13 | 80 |
| Mesh | 15 | 32 |
| Edit Mesh | 22 | 30 |
| Mesh Tools | 22 | 34 |
| Mesh Display | 4 | 38 |
| Curves | 0 | 36 |
| Surfaces | 0 | 41 |
| Deform | 0 | 75 |
| UV | 10 | 19 |
| Key | 4 | 36 |
| Playback | 5 | 27 |
| Shift+RMB object | 26 | 47 |
| Shift+RMB vertex | 14 | 26 |
| Shift+RMB edge | 26 | 37 |
| Shift+RMB face | 24 | 36 |
| Shift+RMB default | 7 | 32 |
| zones | 15 | 45 |

## Every row

`✓ id` = Forge's command; `-` = not in Forge yet (a command to build).

### File

- ✓ `newScene` New Scene (Maya: NewScene)
- ✓ `openScene` Open Scene... (Maya: OpenScene)
- ✓ `save` Save Scene (Maya: SaveScene)
- ✓ `saveAs` Save Scene As... (Maya: SaveSceneAs)
- - IncrementAndSave (Maya: IncrementAndSave)
- - Archive Scene (Maya: ArchiveScene)
- - Save Preferences (Maya: SavePreferences)
- - Optimize Scene Size (Maya: OptimizeScene)
- ✓ `importFile` Import... (Maya: Import)
- ✓ `export` Export All... (Maya: Export)
- - Export Selection... (Maya: ExportSelection)
- - Adobe(R) After Effects(R) Live Link (Maya: OpenAELiveLink)
- - Export to Offline File... (Maya: ExportOfflineFile)
- - Assign Offline File... (Maya: AssignOfflineFile)
- - ATOM > Export Animation... (Maya: ExportAnim)
- - ATOM > Import Animation... (Maya: ImportAnim)
- - ATOM > Create ATOM Template... (Maya: ATOMTemplate)
- - Create Reference... (Maya: CreateReference)
- - Reference Editor (Maya: ReferenceEditor)
- - View Image... (Maya: ViewImage)
- - View Sequence... (Maya: ViewSequence)
- - Project Window (Maya: ProjectWindow)
- - Set Project... (Maya: SetProject)
- - Quit (Maya: Quit)

### Edit

- ✓ `undo` Undo (Maya: Undo)
- ✓ `redo` Redo (Maya: Redo)
- ✓ `repeatLast` Repeat (Maya: RepeatLast)
- - Recent Commands List (Maya: RecentCommandsWindow)
- - Cut (Maya: CutSelected)
- - Copy (Maya: CopySelected)
- - Paste (Maya: PasteSelected)
- - Keys > Cut Keys (Maya: CutKeys)
- ✓ `copyAnim` Keys > Copy Keys (Maya: CopyKeys)
- ✓ `pasteAnim` Keys > Paste Keys (Maya: PasteKeys)
- ✓ `deleteKey` Keys > Delete Keys (Maya: DeleteKeys)
- - Keys > Scale Keys (Maya: ScaleKeys)
- - Keys > Snap Keys (Maya: SnapKeys)
- - Keys > $cmd (Maya: $cmd)
- ✓ `delete` Delete (Maya: Delete)
- ✓ `deleteHistory` Delete All by Type > History (Maya: DeleteAllHistory)
- - Delete All by Type > Non-Deformer History (Maya: BakeAllNonDefHistory)
- - Delete All by Type > Channels (Maya: DeleteAllChannels)
- - Delete All by Type > Static Channels (Maya: DeleteAllStaticChannels)
- - Delete All by Type > Clips (Maya: DeleteAllClips)
- - Delete All by Type > Constraints (Maya: DeleteAllConstraints)
- - Delete All by Type > Motion Paths (Maya: DeleteAllMotionPaths)
- - Delete All by Type > Non-particle Expressions (Maya: DeleteAllExpressions)
- - Delete All by Type > Sounds (Maya: DeleteAllSounds)
- - Delete All by Type > IK Handles (Maya: DeleteAllIKHandles)
- - Delete All by Type > Joints (Maya: DeleteAllJoints)
- - Delete All by Type > Clusters (Maya: DeleteAllClusters)
- - Delete All by Type > Lattices (Maya: DeleteAllLattices)
- - Delete All by Type > Nonlinears (Maya: DeleteAllNonLinearDeformers)
- - Delete All by Type > Sculpt Objects (Maya: DeleteAllSculptObjects)
- - Delete All by Type > Wires (Maya: DeleteAllWires)
- - Delete All by Type > Cameras (Maya: DeleteAllCameras)
- - Delete All by Type > Image Planes (Maya: DeleteAllImagePlanes)
- - Delete All by Type > Lights (Maya: DeleteAllLights)
- - Delete All by Type > Shading Groups and Materials (Maya: DeleteAllShadingGroupsAndMaterials)
- - Delete All by Type > Controllers (Maya: DeleteAllControllers)
- - Delete All by Type > Assets (Maya: DeleteAllContainers)
- - Delete All by Type > Fluids (Maya: DeleteAllFluids)
- - Delete All by Type > Particles (Maya: DeleteAllParticles)
- - Delete All by Type > Rigid Bodies (Maya: DeleteAllRigidBodies)
- - Delete All by Type > Rigid Constraints (Maya: DeleteAllRigidConstraints)
- - Delete All by Type > Strokes (Maya: DeleteAllStrokes)
- - Delete All by Type > Dynamic Constraints (Maya: DeleteAllDynamicConstraints)
- - Delete All by Type > nCloths (Maya: DeleteAllNCloths)
- - Delete All by Type > nParticles (Maya: DeleteAllNParticles)
- - Delete All by Type > nRigids (Maya: DeleteAllNRigids)
- ✓ `duplicate` Duplicate (Maya: Duplicate)
- - Duplicate Special (Maya: DuplicateSpecial)
- ✓ `duplicateT` Duplicate with Transform (Maya: DuplicateWithTransform)
- - Transfer Attribute Values (Maya: TransferAttributeValues)
- ✓ `group` Group (Maya: Group)
- ✓ `ungroup` Ungroup (Maya: Ungroup)
- - LOD (Level of Detail) > Create LOD Group (Maya: LevelOfDetailGroup)
- - LOD (Level of Detail) > Generate LOD Meshes (Maya: LODGenerateMeshes)
- - LOD (Level of Detail) > Ungroup LOD Group (Maya: LevelOfDetailUngroup)
- ✓ `parent` Parent (Maya: Parent)
- ✓ `unparent` Unparent (Maya: Unparent)

### Create

- - NURBS Primitives > Sphere (Maya: CreateNURBSSphere)
- - NURBS Primitives > Cube (Maya: CreateNURBSCube)
- - NURBS Primitives > Cylinder (Maya: CreateNURBSCylinder)
- - NURBS Primitives > Cone (Maya: CreateNURBSCone)
- - NURBS Primitives > Plane (Maya: CreateNURBSPlane)
- - NURBS Primitives > Torus (Maya: CreateNURBSTorus)
- - NURBS Primitives > Circle (Maya: CreateNURBSCircle)
- - NURBS Primitives > Square (Maya: CreateNURBSSquare)
- - NURBS Primitives > Interactive Creation (Maya: ToggleCreateNurbsPrimitivesAsTool)
- - NURBS Primitives > Exit On Completion (Maya: ToggleNurbsPrimitivesAsToolExitOnComplete)
- ✓ `sphere` Polygon Primitives > Sphere (Maya: CreatePolygonSphere)
- ✓ `cube` Polygon Primitives > Cube (Maya: CreatePolygonCube)
- ✓ `cylinder` Polygon Primitives > Cylinder (Maya: CreatePolygonCylinder)
- ✓ `cone` Polygon Primitives > Cone (Maya: CreatePolygonCone)
- ✓ `torus` Polygon Primitives > Torus (Maya: CreatePolygonTorus)
- ✓ `plane` Polygon Primitives > Plane (Maya: CreatePolygonPlane)
- - Polygon Primitives > Polygon Disc (Maya: CreatePolygonDisc)
- - Polygon Primitives > Platonic Solid (Maya: CreatePolygonPlatonic)
- - Polygon Primitives > Pyramid (Maya: CreatePolygonPyramid)
- - Polygon Primitives > Prism (Maya: CreatePolygonPrism)
- - Polygon Primitives > Pipe (Maya: CreatePolygonPipe)
- - Polygon Primitives > Helix (Maya: CreatePolygonHelix)
- - Polygon Primitives > Gear (Maya: CreatePolygonGear)
- - Polygon Primitives > Soccer Ball (Maya: CreatePolygonSoccerBall)
- - Polygon Primitives > Super Ellipse (Maya: CreatePolygonSuperEllipse)
- - Polygon Primitives > Spherical Harmonics (Maya: CreatePolygonSphericalHarmonics)
- - Polygon Primitives > Ultra Shape (Maya: CreatePolygonUltraShape)
- - Polygon Primitives > Interactive Creation (Maya: ToggleCreatePolyPrimitivesAsTool)
- - Polygon Primitives > Exit On Completion (Maya: TogglePolyPrimitivesAsToolExitOnComplete)
- - Subdiv Primitives > Sphere (Maya: CreateSubdivSphere)
- - Subdiv Primitives > Cube (Maya: CreateSubdivCube)
- - Subdiv Primitives > Cylinder (Maya: CreateSubdivCylinder)
- - Subdiv Primitives > Cone (Maya: CreateSubdivCone)
- - Subdiv Primitives > Plane (Maya: CreateSubdivPlane)
- - Subdiv Primitives > Torus (Maya: CreateSubdivTorus)
- - Volume Primitives > Sphere (Maya: CreateVolumeSphere)
- - Volume Primitives > Cube (Maya: CreateVolumeCube)
- - Volume Primitives > Cone (Maya: CreateVolumeCone)
- - Lights > Ambient Light (Maya: CreateAmbientLight)
- - Lights > Directional Light (Maya: CreateDirectionalLight)
- - Lights > Point Light (Maya: CreatePointLight)
- - Lights > Spot Light (Maya: CreateSpotLight)
- - Lights > Area Light (Maya: CreateAreaLight)
- - Lights > Volume Light (Maya: CreateVolumeLight)
- - Curve Tools > CV Curve Tool (Maya: CVCurveTool)
- - Curve Tools > EP Curve Tool (Maya: EPCurveTool)
- - Curve Tools > Bezier Curve Tool (Maya: CreateBezierCurveTool)
- - Curve Tools > Pencil Curve Tool (Maya: PencilCurveTool)
- - Curve Tools > Three Point Circular Arc (Maya: ThreePointArcTool)
- - Curve Tools > Two Point Circular Arc (Maya: TwoPointArcTool)
- - Polygon Type (Maya: CreatePolygonType)
- - SVG (Maya: CreatePolygonSVG)
- - Adobe(R) Illustrator(R) Object... (Maya: CreateIllustratorCurves)
- - Construction Plane (Maya: CreateConstructionPlane)
- ✓ `imagePlane` Free Image Plane (Maya: CreateImagePlane)
- - Locator (Maya: CreateLocator)
- - Annotation... (Maya: CreateAnnotateNode)
- - Measure Tools > Distance Tool (Maya: DistanceTool)
- - Measure Tools > Parameter Tool (Maya: ParameterTool)
- - Measure Tools > Arc Length Tool (Maya: ArcLengthTool)
- - Empty Group (Maya: CreateEmptyGroup)
- - Sets > Set (Maya: CreateSet)
- - Sets > Partition (Maya: CreatePartition)
- ✓ `quickSet` Sets > Quick Select Set... (Maya: CreateQuickSelectSet)
- - Asset > Create Asset (Maya: CreateContainer)
- - Asset > Create Asset with Transform (Maya: CreateDagContainer)

### Select

- ✓ `selectAll` All (Maya: SelectAll)
- - All by Type > IK Handles (Maya: SelectAllIKHandles)
- - All by Type > Joints (Maya: SelectAllJoints)
- - All by Type > Clusters (Maya: SelectAllClusters)
- - All by Type > Lattices (Maya: SelectAllLattices)
- - All by Type > Sculpt Objects (Maya: SelectAllSculptObjects)
- - All by Type > Wires (Maya: SelectAllWires)
- - All by Type > Transforms (Maya: SelectAllTransforms)
- - All by Type > Geometry (Maya: SelectAllGeometry)
- - All by Type > NURBS Curves (Maya: SelectAllNURBSCurves)
- - All by Type > NURBS Surfaces (Maya: SelectAllNURBSSurfaces)
- - All by Type > Polygon Geometry (Maya: SelectAllPolygonGeometry)
- - All by Type > Cameras (Maya: SelectAllCameras)
- - All by Type > Lights (Maya: SelectAllLights)
- - All by Type > Image Planes (Maya: SelectAllImagePlanes)
- - All by Type > Assets (Maya: SelectAllAssets)
- - All by Type > Fluids (Maya: SelectAllFluids)
- - All by Type > Particles (Maya: SelectAllParticles)
- - All by Type > Rigid Bodies (Maya: SelectAllRigidBodies)
- - All by Type > Rigid Constraints (Maya: SelectAllRigidConstraints)
- - All by Type > Brushes (Maya: SelectAllBrushes)
- - All by Type > Strokes (Maya: SelectAllStrokes)
- - All by Type > Dynamic Constraints (Maya: SelectAllDynamicConstraints)
- - All by Type > Follicles (Maya: SelectAllFollicles)
- - All by Type > nCloths (Maya: SelectAllNCloths)
- - All by Type > nParticles (Maya: SelectAllNParticles)
- - All by Type > nRigids (Maya: SelectAllNRigids)
- ✓ `selectNone` Deselect All (Maya: SelectNone)
- ✓ `hierarchy` Hierarchy (Maya: SelectHierarchy)
- ✓ `invert` Inverse (Maya: InvertSelection)
- ✓ `selectSimilar` Similar (Maya: SelectSimilar)
- ✓ `grow` Grow (Maya: GrowPolygonSelectionRegion)
- ✓ `growLoop` Grow Along Loop (Maya: GrowLoopPolygonSelectionRegion)
- ✓ `shrink` Shrink (Maya: ShrinkPolygonSelectionRegion)
- ✓ `shrinkLoop` Shrink Along Loop (Maya: ShrinkLoopPolygonSelectionRegion)
- ✓ `objComp` Object/Component (Maya: SelectToggleMode)
- - Components > Multi-Component (Maya: SelectMultiComponentMask)
- ✓ `vertex` Components > Vertex (Maya: SelectVertexMask)
- ✓ `edge` Components > Edge (Maya: SelectEdgeMask)
- ✓ `face` Components > Face (Maya: SelectFacetMask)
- - Components > Vertex Face (Maya: SelectVertexFaceMask)
- ✓ `uv` Components > UV (Maya: SelectUVMask)
- ✓ `uvShell` Components > UV Shell (Maya: SelectMeshUVShell)
- ✓ `contiguousEdges` Contiguous Edges (Maya: SelectContiguousEdges)
- ✓ `shortestPath` Shortest Edge Path Tool (Maya: SelectShortestEdgePathTool)
- ✓ `convertToVerts` Convert Selection > To Vertices (Maya: ConvertSelectionToVertices)
- - Convert Selection > To Vertex Faces (Maya: ConvertSelectionToVertexFaces)
- ✓ `convertToVertexPerimeter` Convert Selection > To Vertex Perimeter (Maya: ConvertSelectionToVertexPerimeter)
- ✓ `convertToEdges` Convert Selection > To Edges (Maya: ConvertSelectionToEdges)
- ✓ `loopSel` Convert Selection > To Edge Loop (Maya: SelectEdgeLoopSp)
- ✓ `ringSel` Convert Selection > To Edge Ring (Maya: SelectEdgeRingSp)
- ✓ `convertToContainedEdges` Convert Selection > To Contained Edges (Maya: ConvertSelectionToContainedEdges)
- ✓ `convertToEdgePerimeter` Convert Selection > To Edge Perimeter (Maya: ConvertSelectionToEdgePerimeter)
- ✓ `convertToFaces` Convert Selection > To Faces (Maya: ConvertSelectionToFaces)
- - Convert Selection > To Face Path (Maya: SelectFacePath)
- ✓ `convertToContainedFaces` Convert Selection > To Contained Faces (Maya: ConvertSelectionToContainedFaces)
- ✓ `convertToFacePerimeter` Convert Selection > To Face Perimeter (Maya: ConvertSelectionToFacePerimeter)
- ✓ `toUV` Convert Selection > To UVs (Maya: ConvertSelectionToUVs)
- - Convert Selection > To UV Shell (Maya: ConvertSelectionToUVShell)
- - Convert Selection > To UV Shell Border (Maya: ConvertSelectionToUVShellBorder)
- - Convert Selection > To UV Perimeter (Maya: ConvertSelectionToUVPerimeter)
- - Convert Selection > To UV Edge Loop (Maya: ConvertSelectionToUVEdgeLoop)
- ✓ `convertToShell` Convert Selection > To Shell (Maya: ConvertSelectionToShell)
- ✓ `convertToShellBorder` Convert Selection > To Shell Border (Maya: ConvertSelectionToShellBorder)
- - Use Constraints... (Maya: PolygonSelectionConstraints)
- - Components > Control Vertex (Maya: SelectCVsMask)
- - Components > Curve Point (Maya: SelectCurvePointsMask)
- - Components > Edit Point (Maya: SelectPointsMask)
- - Components > Hull (Maya: SelectHullsMask)
- - All CVs (Maya: SelectCurveCVsAll)
- - First CV (Maya: SelectCurveCVsFirst)
- - Last CV (Maya: SelectCurveCVsLast)
- - Cluster Curve (Maya: ClusterCurve)
- - Components > Control Vertex (Maya: SelectCVsMask)
- - Components > Hull (Maya: SelectHullsMask)
- - Components > Isoparm (Maya: SelectLinesMask)
- - Components > Surface Point (Maya: SelectSurfacePointsMask)
- - CV Selection Boundary (Maya: SelectCVSelectionBoundary)
- - Surface Border (Maya: SelectSurfaceBorder)

### Modify

- ✓ `move` Transformation Tools > Move Tool (Maya: MoveTool)
- ✓ `rotate` Transformation Tools > Rotate Tool (Maya: RotateTool)
- ✓ `scale` Transformation Tools > Scale Tool (Maya: ScaleTool)
- - Transformation Tools > Type Manipulator (Maya: EditPolygonType)
- - Transformation Tools > Universal Manipulator (Maya: UniversalManip)
- - Transformation Tools > Move Normal Tool (Maya: MoveNormalTool)
- - Transformation Tools > Move/Rotate/Scale Tool (Maya: MoveRotateScaleTool)
- ✓ `showManip` Transformation Tools > Show Manipulator Tool (Maya: ShowManipulatorTool)
- - Transformation Tools > Default Object Manipulator > None (Maya: SetDefaultManipNone)
- - Transformation Tools > Default Object Manipulator > Move (Maya: SetDefaultManipMove)
- - Transformation Tools > Default Object Manipulator > Rotate (Maya: SetDefaultManipRotate)
- - Transformation Tools > Default Object Manipulator > Scale (Maya: SetDefaultManipScale)
- - Transformation Tools > Default Object Manipulator > Transform (Maya: SetDefaultManipTransform)
- - Transformation Tools > Proportional Modification Tool (Maya: ProportionalModificationTool)
- - Transformation Tools > Soft Modification Tool (Maya: SoftModTool)
- ✓ `resetXf` Reset Transformations (Maya: ResetTransformations)
- ✓ `freeze` Freeze Transformations (Maya: FreezeTransformations)
- - Match Transformations > Match All Transforms (Maya: MatchTransform)
- - Match Transformations > Match Translation (Maya: MatchTranslation)
- - Match Transformations > Match Rotation (Maya: MatchRotation)
- - Match Transformations > Match Scaling (Maya: MatchScaling)
- - Match Transformations > Match Pivots (Maya: MatchPivots)
- ✓ `centerPivot` Center Pivot (Maya: CenterPivot)
- ✓ `resetPivot` Zero Pivot (Maya: ZeroPivot)
- - Bake Pivot (Maya: BakeCustomPivot)
- - Snap Align Objects > Point to Point (Maya: SnapPointToPoint)
- - Snap Align Objects > 2 Points to 2 Points (Maya: Snap2PointsTo2Points)
- - Snap Align Objects > 3 Points to 3 Points (Maya: Snap3PointsTo3Points)
- - Snap Align Objects > Align Objects (Maya: AlignObjects)
- - Snap Align Objects > Position Along Curve (Maya: PositionAlongCurve)
- - Align Tool (Maya: SetAlignTool)
- - Snap Together Tool (Maya: SetSnapTogetherTool)
- - Reorder Rotation... (Maya: ReorderRotationDialog)
- - Evaluate Nodes > Evaluate All (Maya: EnableAll)
- - Evaluate Nodes > Ignore All (Maya: DisableAll)
- - Evaluate Nodes > IK Solvers (Maya: EnableIKSolvers)
- - Evaluate Nodes > Constraints (Maya: EnableConstraints)
- - Evaluate Nodes > Expressions (Maya: EnableExpressions)
- - Evaluate Nodes > Fluids (Maya: EnableFluids)
- - Evaluate Nodes > Global Stitch (Maya: EnableGlobalStitch)
- - Evaluate Nodes > nCloths (Maya: EnableNCloths)
- - Evaluate Nodes > nParticles (Maya: EnableNParticles)
- - Evaluate Nodes > nRigids (Maya: EnableNRigids)
- - Evaluate Nodes > Dynamic Constraints (Maya: EnableDynamicConstraints)
- - Evaluate Nodes > nucleuses (Maya: EnableNucleuses)
- - Evaluate Nodes > Particles (Maya: EnableParticles)
- - Evaluate Nodes > Rigid Bodies (Maya: EnableRigidBodies)
- - Evaluate Nodes > Snapshots (Maya: EnableSnapshots)
- - Prefix Hierarchy Names... (Maya: PrefixHierarchyNames)
- - Search and Replace Names... (Maya: SearchAndReplaceNames)
- - Add Attribute... (Maya: AddAttribute)
- - Edit Attribute... (Maya: RenameAttribute)
- - Delete Attribute... (Maya: DeleteAttribute)
- ✓ `makeLive` Make Live (Maya: MakeLive)
- - Replace Objects (Maya: ReplaceObjects)
- - Convert > NURBS to Polygons (Maya: NURBSToPolygons)
- - Convert > NURBS to Subdiv (Maya: CreateSubdivSurface)
- - Convert > Polygons to Subdiv (Maya: CreateSubdivSurfacePoly)
- - Convert > Smooth Mesh Preview to Polygons (Maya: CreatePolyFromPreview)
- - Convert > Polygon Edges to Curve (Maya: CreateCurveFromPoly)
- - Convert > Type to Curves (Maya: ConvertTypeCapsToCurves)
- - Convert > Subdiv to Polygons (Maya: TesselateSubdivSurface)
- - Convert > Subdiv to NURBS (Maya: SubdivToNURBS)
- - Convert > NURBS Curve to Bezier (Maya: NurbsCurveToBezier)
- - Convert > Bezier Curve to NURBS (Maya: BezierCurveToNurbs)
- - Convert > Paint Effects to Polygons (Maya: PaintEffectsToPoly)
- - Convert > Paint Effects to NURBS (Maya: PaintEffectsToNurbs)
- - Convert > Paint Effects to Curves (Maya: PaintEffectsToCurve)
- - Convert > Texture to Geometry (Maya: TextureToGeometry)
- - Convert > Displacement to Polygons (Maya: DisplacementToPolygon)
- - Convert > Displacement to Polygons with History (Maya: SetupAnimatedDisplacement)
- - Convert > Fluid to Polygons (Maya: FluidsToPolygons)
- - Convert > nParticle to Polygons (Maya: NParticleToPolygons)
- - Convert > Instance to Object (Maya: ConvertInstanceToObject)
- - Convert > Geometry to Bounding Box (Maya: GeometryToBoundingBox)
- - Paint Scripts Tool (Maya: ScriptPaintTool)
- - Paint Attributes Tool (Maya: ArtPaintAttrTool)
- - Asset > Add to Asset (Maya: AddToContainer)
- - Asset > Remove from Asset (Maya: RemoveFromContainer)
- - Asset > Export Proxy Asset... (Maya: ExportProxyContainer)
- - Asset > Publish Attributes (Maya: PublishAttributes)
- - Asset > Unpublish Attributes (Maya: UnpublishAttributes)
- - Asset > Publish Connections (Maya: PublishConnections)
- - Asset > Lock Unpublished Attributes (Maya: LockContainer)
- - Asset > Unlock Unpublished Attributes (Maya: UnlockContainer)
- - Asset > Publish Node (Maya: PublishNode)
- - Asset > Unpublish Node (Maya: UnpublishNode)
- - Asset > Assign Template... (Maya: AssignTemplate)
- - Asset > Select Asset Contents (Maya: SelectContainerContents)
- - Asset > Advanced Assets > Node Publishing > Publish as Selection Transform (Maya: PublishRootTransform)
- - Asset > Advanced Assets > Node Publishing > Publish Parent Anchor (Maya: PublishParentAnchor)
- - Asset > Advanced Assets > Node Publishing > Publish Child Anchor (Maya: PublishChildAnchor)
- - Asset > Advanced Assets > Node Unpublishing > Unpublish Selection Transform (Maya: UnpublishRootTransform)
- - Asset > Advanced Assets > Node Unpublishing > Unpublish Parent Anchor (Maya: UnpublishParentAnchor)
- - Asset > Advanced Assets > Node Unpublishing > Unpublish Child Anchor (Maya: UnpublishChildAnchor)

### Display

- ✓ `grid` Grid (Maya: ToggleGrid)
- - Heads Up Display > Animation Details (Maya: ToggleAnimationDetails)
- - Heads Up Display > Camera Names (Maya: ToggleCameraNames)
- - Heads Up Display > Caps Lock (Maya: ToggleCapsLockDisplay)
- - Heads Up Display > Current Asset (Maya: ToggleCurrentContainerHud)
- - Heads Up Display > Current Frame (Maya: ToggleCurrentFrame)
- - Heads Up Display > Evaluation (Maya: ToggleEvaluationManagerVisibility)
- - Heads Up Display > Focal Length (Maya: ToggleFocalLength)
- - Heads Up Display > Frame Rate (Maya: ToggleFrameRate)
- - Heads Up Display > HIK Details (Maya: ToggleHikDetails)
- - Heads Up Display > Material Loading Details (Maya: ToggleMaterialLoadingDetailsVisibility)
- - Heads Up Display > Object Details (Maya: ToggleObjectDetails)
- - Heads Up Display > Origin Axis (Maya: ToggleOriginAxis)
- - Heads Up Display > Particle Count (Maya: ToggleParticleCount)
- - Heads Up Display > Poly Count (Maya: TogglePolyCount)
- - Heads Up Display > Scene Timecode (Maya: ToggleSceneTimecode)
- - Heads Up Display > Select Details (Maya: ToggleSelectDetails)
- - Heads Up Display > Subdiv Details (Maya: ToggleSubdDetails)
- - Heads Up Display > Symmetry (Maya: ToggleSymmetryDisplay)
- - Heads Up Display > View Axis (Maya: ToggleViewAxis)
- - Heads Up Display > ViewCube (Maya: ToggleViewCube)
- - Heads Up Display > Viewport Renderer (Maya: ToggleViewportRenderer)
- - Heads Up Display > In-view Messages (Maya: ToggleInViewMessage)
- ✓ `iveToggle` Heads Up Display > In-View Editors (Maya: ToggleInViewEditor)
- ✓ `hide` Hide > Hide Selection (Maya: HideSelectedObjects)
- ✓ `hideOthers` Hide > Hide Unselected Objects (Maya: HideUnselectedObjects)
- - Hide > Hide Unselected CVs (Maya: HideUnselectedCVs)
- - Hide > All (Maya: HideAll)
- - Hide > Hide Controllers (Maya: HideControllers)
- - Hide > Hide Geometry > All (Maya: HideGeometry)
- - Hide > Hide Geometry > NURBS Surfaces (Maya: HideNURBSSurfaces)
- - Hide > Hide Geometry > NURBS Curves (Maya: HideNURBSCurves)
- - Hide > Hide Geometry > Polygon Surfaces (Maya: HidePolygonSurfaces)
- - Hide > Hide Geometry > Deforming Geometry (Maya: HideDeformingGeometry)
- - Hide > Hide Geometry > Subdiv Surfaces (Maya: HideSubdivSurfaces)
- - Hide > Hide Geometry > Strokes (Maya: HideStrokes)
- - Hide > Hide Geometry > Stroke Path Curves (Maya: HideStrokePathCurves)
- - Hide > Hide Geometry > Stroke Control Curves (Maya: HideStrokeControlCurves)
- - Hide > Hide Kinematics > All (Maya: HideKinematics)
- - Hide > Hide Kinematics > Joints (Maya: HideJoints)
- - Hide > Hide Kinematics > IK Handles (Maya: HideIKHandles)
- - Hide > Hide Deformers > All (Maya: HideDeformers)
- - Hide > Hide Deformers > Lattices (Maya: HideLattices)
- - Hide > Hide Deformers > Sculpt Objects (Maya: HideSculptObjects)
- - Hide > Hide Deformers > Clusters (Maya: HideClusters)
- - Hide > Hide Deformers > Nonlinears (Maya: HideNonlinears)
- - Hide > Hide Deformers > Wrap Influences (Maya: HideWrapInfluences)
- - Hide > Hide Deformers > Smooth Skin Influences (Maya: HideSmoothSkinInfluences)
- - Hide > Lights (Maya: HideLights)
- - Hide > Cameras (Maya: HideCameras)
- - Hide > Texture Placements (Maya: HideTexturePlacements)
- - Hide > Construction Planes (Maya: HidePlanes)
- - Hide > Fluids (Maya: HideFluids)
- - Hide > Hair Systems (Maya: HideHairSystems)
- - Hide > Follicles (Maya: HideFollicles)
- - Hide > Fur (Maya: HideFur)
- - Hide > nCloths (Maya: HideNCloths)
- - Hide > nParticles (Maya: HideNParticles)
- - Hide > nRigids (Maya: HideNRigids)
- - Hide > Dynamic Constraints (Maya: HideDynamicConstraints)
- - Hide > Animation Markers (Maya: HideMarkers)
- - Hide > Light Manipulators (Maya: HideLightManipulators)
- - Hide > Camera Manipulators (Maya: HideCameraManipulators)
- ✓ `show` Show > Show Selection (Maya: ShowSelectedObjects)
- ✓ `showLast` Show > Show Last Hidden (Maya: ShowLastHidden)
- - Show > All Surface CVs (Maya: ShowSurfaceCVs)
- - Show > All Components (Maya: ShowAllPolyComponents)
- ✓ `showAll` Show > All (Maya: ShowAll)
- - Show > Show Controllers (Maya: ShowControllers)
- - Show > Show Geometry > All (Maya: ShowGeometry)
- - Show > Show Geometry > NURBS Surfaces (Maya: ShowNURBSSurfaces)
- - Show > Show Geometry > NURBS Curves (Maya: ShowNURBSCurves)
- - Show > Show Geometry > Polygon Surfaces (Maya: ShowPolygonSurfaces)
- - Show > Show Geometry > Deforming Geometry (Maya: ShowDeformingGeometry)
- - Show > Show Geometry > Subdiv Surfaces (Maya: ShowSubdivSurfaces)
- - Show > Show Geometry > Strokes (Maya: ShowStrokes)
- - Show > Show Geometry > Stroke Path Curves (Maya: ShowStrokePathCurves)
- - Show > Show Geometry > Stroke Control Curves (Maya: ShowStrokeControlCurves)
- - Show > Show Kinematics > All (Maya: ShowKinematics)
- - Show > Show Kinematics > Joints (Maya: ShowJoints)
- - Show > Show Kinematics > IK Handles (Maya: ShowIKHandles)
- - Show > Show Deformers > All (Maya: ShowDeformers)
- - Show > Show Deformers > Lattices (Maya: ShowLattices)
- - Show > Show Deformers > Sculpt Objects (Maya: ShowSculptObjects)
- - Show > Show Deformers > Clusters (Maya: ShowClusters)
- - Show > Show Deformers > Nonlinears (Maya: ShowNonlinears)
- - Show > Show Deformers > Wrap Influences (Maya: ShowWrapInfluences)
- - Show > Show Deformers > Smooth Skin Influences (Maya: ShowSmoothSkinInfluences)
- - Show > Lights (Maya: ShowLights)
- - Show > Cameras (Maya: ShowCameras)
- - Show > Texture Placements (Maya: ShowTexturePlacements)
- - Show > Construction Planes (Maya: ShowPlanes)
- - Show > Fluids (Maya: ShowFluids)
- - Show > Hair Systems (Maya: ShowHairSystems)
- - Show > Follicles (Maya: ShowFollicles)
- - Show > Fur (Maya: ShowFur)
- - Show > nCloths (Maya: ShowNCloths)
- - Show > nParticles (Maya: ShowNParticles)
- - Show > nRigids (Maya: ShowNRigids)
- - Show > Dynamic Constraints (Maya: ShowDynamicConstraints)
- - Show > Animation Markers (Maya: ShowMarkers)
- - Show > Light Manipulators (Maya: ShowLightManipulators)
- - Show > Camera Manipulators (Maya: ShowCameraManipulators)
- ✓ `hideToggle` Toggle Show/Hide (Maya: ToggleVisibilityAndKeepSelection)
- - Wireframe Color... (Maya: SetWireframeColor)
- - Object Display > Template (Maya: TemplateObject)
- - Object Display > Untemplate (Maya: UntemplateObject)
- - Object Display > Bounding Box (Maya: ShowBoundingBox)
- - Object Display > No Bounding Box (Maya: HideBoundingBox)
- - Object Display > Geometry (Maya: ShowObjectGeometry)
- - Object Display > No Geometry (Maya: HideObjectGeometry)
- - Object Display > Ignore Hardware Shader (Maya: IgnoreHardwareShader)
- - Object Display > Use Hardware Shader (Maya: UseHardwareShader)
- - Object Display > Fast Interaction (Maya: ToggleFastInteraction)
- - Transform Display > Local Rotation Axes (Maya: ToggleLocalRotationAxes)
- - Transform Display > Rotate Pivots (Maya: ToggleRotationPivots)
- - Transform Display > Scale Pivots (Maya: ToggleScalePivots)
- - Transform Display > Selection Handles (Maya: ToggleSelectionHandles)
- ✓ `frameAll` Frame All in All Views (Maya: FrameAllInAllViews)
- ✓ `frameSel` Frame Selection in All Views (Maya: FrameSelectedWithoutChildrenInAllViews)
- - Frame Selection with Children in All Views (Maya: FrameSelectedInAllViews)

### Windows

- - AttributeEditor (Maya: AttributeEditor)
- ✓ `winChannel` OpenChannelsLayers (Maya: OpenChannelsLayers)
- ✓ `winChannel` OpenChannelBox (Maya: OpenChannelBox)
- ✓ `layerEditor` OpenLayerEditor (Maya: OpenLayerEditor)
- - Tool Settings (Maya: ToolSettingsWindow)
- - Hypergraph: Hierarchy (Maya: HypergraphHierarchyWindow)
- - Hypergraph: Connections (Maya: HypergraphDGWindow)
- - Viewport (Maya: DisplayViewport)
- - Adobe(R) After Effects(R) Live Link (Maya: OpenAELiveLink)
- - Asset Editor (Maya: AssetEditor)
- - Attribute Spread Sheet (Maya: SpreadSheetEditor)
- - Component Editor (Maya: ComponentEditor)
- - Connection Editor (Maya: ConnectionEditor)
- - Channel Control (Maya: ChannelControlEditor)
- ✓ `layerEditor` Display Layer Editor (Maya: DisplayLayerEditorWindow)
- - File Path Editor (Maya: FilePathEditor)
- - Namespace Editor (Maya: NamespaceEditor)
- - Script Editor (Maya: ScriptEditor)
- - Command Shell (Maya: CommandShell)
- - DG Profiler (Maya: OpenDGProfiler)
- - Profiler (Maya: ProfilerTool)
- - Evaluation Toolkit (Maya: EvaluationToolkit)
- ✓ `winToolkit` Modeling Toolkit (Maya: OpenModelingToolkit)
- - Paint Effects (Maya: PaintEffectsWindow)
- ✓ `uvEditor` UV Editor (Maya: TextureViewWindow)
- - XGen Editor (Maya: OpenXGenEditor)
- - Crease Sets (Maya: OpenCreaseEditor)
- ✓ `renderDialog` RenderViewWindow (Maya: RenderViewWindow)
- - RenderGlobalsWindow (Maya: RenderGlobalsWindow)
- ✓ `winMaterials` Hypershade (Maya: HypershadeWindow)
- - Render Layer Editor (Maya: RenderLayerEditorWindow)
- - Render Setup (Maya: RenderSetupWindow)
- - Light Editor (Maya: OpenLightEditor)
- - Custom Stereo Rig Editor (Maya: OpenStereoRigManager)
- - Rendering Flags (Maya: RenderFlagsWindow)
- - Shading Group Attributes (Maya: ShadingGroupAttributeEditor)
- - Hardware Render Buffer (Maya: HardwareRenderBuffer)
- ✓ `graphEditor` Graph Editor (Maya: GraphEditor)
- - Dope Sheet (Maya: DopeSheetEditor)
- - Time Editor (Maya: TimeEditorWindow)
- - MotionMaker Editor (Maya: OpenMotionMaker)
- - Sequencer (Maya: SequenceEditor)
- - Trax Editor (Maya: CharacterAnimationEditor)
- - Motion Trail Editor (Maya: OpenMotionTrailEditor)
- - Quick Rig (Maya: QuickRigEditor)
- - HumanIK (Maya: HIKCharacterControlsTool)
- - ShapeEditor (Maya: ShapeEditor)
- - PoseEditor (Maya: PoseEditor)
- - Expression Editor (Maya: ExpressionEditor)
- - Light-Centric (Maya: LightCentricLightLinkingEditor)
- - Object-Centric (Maya: ObjectCentricLightLinkingEditor)
- - Texture-Centric (Maya: TextureCentricUVLinkingEditor)
- - UV-Centric (Maya: UVCentricUVLinkingEditor)
- - Paint Effects/UV (Maya: PFXUVSetLinkingEditor)
- - Hair/UV (Maya: HairUVSetLinkingEditor)
- - FurUVSetLinkingEditor (Maya: FurUVSetLinkingEditor)
- - Animation Layers (Maya: AnimLayerRelationshipEditor)
- - Camera Sets (Maya: CameraSetEditor)
- - Character Sets (Maya: CharacterSetEditor)
- - Deformer Sets (Maya: DeformerSetEditor)
- - Display Layers (Maya: LayerRelationshipEditor)
- - Dynamic Relationships (Maya: DynamicRelationshipEditor)
- - HairFurRelationshipEditor (Maya: HairFurRelationshipEditor)
- - Partitions (Maya: PartitionEditor)
- - Render Layers (Maya: RenderLayerRelationshipEditor)
- - Render Pass Sets (Maya: RenderPassSetEditor)
- ✓ `setEditor` Sets (Maya: SetEditor)
- ✓ `preferences` Preferences (Maya: PreferencesWindow)
- - Performance Settings (Maya: PerformanceSettingsWindow)
- ✓ `hotkeyEditor` Hotkey Editor (Maya: HotkeyPreferencesWindow)
- - Color Settings (Maya: ColorPreferencesWindow)
- - Marking Menu Editor (Maya: MarkingMenuPreferencesWindow)
- - Shelf Editor (Maya: ShelfPreferencesWindow)
- - Panel Editor (Maya: PanelPreferencesWindow)
- - ML Toolkit (Maya: MLTKWindow)
- - Plug-in Manager (Maya: PluginManager)
- ✓ `winOutliner` Outliner (Maya: OutlinerWindow)
- - Node Editor (Maya: NodeEditorWindow)
- - Content Browser (Maya: OpenContentBrowser)
- - Playblast (Maya: PlayblastWindow)

### Mesh

- ✓ `boolUnion` Booleans > Union (Maya: PolygonBooleanUnion)
- ✓ `boolDifference` Booleans > Difference (A - B) (Maya: PolygonBooleanDifference)
- ✓ `boolDifferenceBA` Booleans > Difference (B - A) (Maya: PolygonBooleanDifferenceBA)
- ✓ `boolIntersection` Booleans > Intersection (Maya: PolygonBooleanIntersection)
- - Booleans > Slice (Maya: PolygonBooleanSlice)
- - Booleans > Hole Punch (Maya: PolygonBooleanHolePunch)
- - Booleans > Cut Out (Maya: PolygonBooleanCutOut)
- - Booleans > Split Edges (Maya: PolygonBooleanSplitEdges)
- ✓ `combine` Combine (Maya: CombinePolygons)
- ✓ `separate` Separate (Maya: SeparatePolygon)
- - Conform (Maya: ConformPolygon)
- ✓ `fillHole` Fill Hole (Maya: FillHole)
- ✓ `sculptReduce` Reduce (Maya: ReducePolygon)
- ✓ `sculptRemesh` Remesh (Maya: PolyRemesh)
- ✓ `sculptQuadRemesh` Retopologize (Maya: PolyRetopo)
- ✓ `smooth` Smooth (Maya: SmoothPolygon)
- - Unsmooth (Maya: UnsmoothPolygon)
- ✓ `triangulate` Triangulate (Maya: Triangulate)
- ✓ `quadrangulate` Quadrangulate (Maya: Quadrangulate)
- ✓ `mirror` Mirror (Maya: MirrorPolygonGeometry)
- - Clipboard Actions > Copy Attributes (Maya: PolygonCopy)
- - Clipboard Actions > Paste Attributes (Maya: PolygonPaste)
- - Clipboard Actions > Clear Clipboard (Maya: PolygonClearClipboard)
- - Transfer Attributes (Maya: TransferAttributes)
- - Transfer Shading Sets (Maya: TransferShadingSets)
- - Transfer Vertex Order (Maya: TransferVertexOrder)
- ✓ `cleanup` Cleanup... (Maya: CleanupPolygon)
- - Smooth Proxy > Subdiv Proxy (Maya: SmoothProxy)
- - Smooth Proxy > Remove Subdiv Proxy Mirror (Maya: UnmirrorSmoothProxy)
- - Smooth Proxy > Crease Tool (Maya: PolyCreaseTool)
- - Smooth Proxy > Toggle Proxy Display (Maya: SmoothingDisplayToggle)
- - Smooth Proxy > Both Proxy and Subdiv Display (Maya: SmoothingDisplayShowBoth)

### Edit Mesh

- ✓ `addDivisions` Add Divisions (Maya: SubdividePolygon)
- ✓ `bevel` Bevel (Maya: BevelPolygon)
- - Smart Bevel (Maya: PolySmartBevel)
- ✓ `bridge` Bridge (Maya: BridgeOrFill)
- ✓ `circularize` Circularize (Maya: PolyCircularize)
- ✓ `collapse` Collapse (Maya: PolygonCollapse)
- ✓ `connect` Connect (Maya: ConnectComponents)
- ✓ `detach` Detach (Maya: DetachComponent)
- ✓ `extrude` Extrude (Maya: PolyExtrude)
- - Smart Extrude (Maya: SmartExtrude)
- ✓ `merge` Merge (Maya: PolyMerge)
- ✓ `mergeCenter` Merge to Center (Maya: MergeToCenter)
- - Transform (Maya: MovePolygonComponent)
- ✓ `flipMesh` Flip (Maya: FlipMesh)
- ✓ `symmetrize` Symmetrize (Maya: Symmetrize)
- ✓ `averageVerts` Average Vertices (Maya: AverageVertex)
- ✓ `chamfer` Chamfer Vertices (Maya: ChamferVertex)
- - Reorder Vertices (Maya: ReorderVertex)
- ✓ `deleteEdgeVert` Delete Edge/Vertex (Maya: DeletePolyElements)
- - Edit Edge Flow (Maya: PolyEditEdgeFlow)
- ✓ `flipTriangleEdge` Flip Triangle Edge (Maya: FlipTriangleEdge)
- ✓ `spinEdgeBack` Spin Edge Backward (Maya: PolySpinEdgeBackward)
- ✓ `spinEdge` Spin Edge Forward (Maya: PolySpinEdgeForward)
- - Assign Invisible Faces (Maya: PolyAssignSubdivHole)
- ✓ `duplicateFace` Duplicate (Maya: DuplicateFace)
- ✓ `extractFace` Extract (Maya: ExtractFace)
- ✓ `poke` Poke (Maya: PokePolygon)
- ✓ `wedge` Wedge (Maya: WedgePolygon)
- - Project Curve on Mesh (Maya: ProjectCurveOnMesh)
- - Split Mesh with Projected Curve (Maya: SplitMeshWithProjectedCurve)

### Mesh Tools

- ✓ `winToolkit` Show/Hide Modeling Toolkit (Maya: ToggleModelingToolkit)
- - Connect (Maya: EnterConnectTool)
- - Crease Tool (Maya: PolyCreaseTool)
- ✓ `insertLoopTool` Insert Edge Loop (Maya: SplitEdgeRingTool)
- - Make Hole (Maya: MakeHoleTool)
- ✓ `multiCut` Multi-Cut (Maya: MultiCutTool)
- ✓ `offsetEdgeLoop` Offset Edge Loop (Maya: DuplicateEdges)
- - Paint Reduce Weights (Maya: PaintReduceWeightsTool)
- - Paint Transfer Attributes (Maya: PaintTransferAttributes)
- ✓ `quadDraw` Quad Draw (Maya: QuadDrawTool)
- ✓ `sculpt` Sculpting Tools > Sculpt Tool (Maya: SetMeshSculptTool)
- ✓ `mayaSmoothTool` Sculpting Tools > Smooth Tool (Maya: SetMeshSmoothTool)
- ✓ `mayaRelaxTool` Sculpting Tools > Relax Tool (Maya: SetMeshRelaxTool)
- ✓ `mayaGrabTool` Sculpting Tools > Grab Tool (Maya: SetMeshGrabTool)
- ✓ `mayaPinchTool` Sculpting Tools > Pinch Tool (Maya: SetMeshPinchTool)
- ✓ `mayaFlattenTool` Sculpting Tools > Flatten Tool (Maya: SetMeshFlattenTool)
- ✓ `mayaFoamyTool` Sculpting Tools > Foamy Tool (Maya: SetMeshFoamyTool)
- - Sculpting Tools > Spray Tool (Maya: SetMeshSprayTool)
- - Sculpting Tools > Repeat Tool (Maya: SetMeshRepeatTool)
- ✓ `mayaImprintTool` Sculpting Tools > Imprint Tool (Maya: SetMeshImprintTool)
- ✓ `mayaWaxTool` Sculpting Tools > Wax Tool (Maya: SetMeshWaxTool)
- ✓ `mayaScrapeTool` Sculpting Tools > Scrape Tool (Maya: SetMeshScrapeTool)
- ✓ `mayaFillTool` Sculpting Tools > Fill Tool (Maya: SetMeshFillTool)
- ✓ `mayaKnifeTool` Sculpting Tools > Knife Tool (Maya: SetMeshKnifeTool)
- ✓ `mayaSmearTool` Sculpting Tools > Smear Tool (Maya: SetMeshSmearTool)
- ✓ `mayaBulgeTool` Sculpting Tools > Bulge Tool (Maya: SetMeshBulgeTool)
- - Sculpting Tools > Amplify Tool (Maya: SetMeshAmplifyTool)
- ✓ `mayaFreezeTool` Sculpting Tools > Freeze Tool (Maya: SetMeshFreezeTool)
- - Sculpting Tools > Smooth Target Tool (Maya: SetMeshSmoothTargetTool)
- - Sculpting Tools > Clone Target Tool (Maya: SetMeshCloneTargetTool)
- - Sculpting Tools > Mask Target Tool (Maya: SetMeshMaskTool)
- - Sculpting Tools > Erase Target Tool (Maya: SetMeshEraseTool)
- ✓ `slideEdge` Slide Edge (Maya: SlideEdgeTool)
- ✓ `targetWeld` Target Weld (Maya: MergeVertexTool)

### Mesh Display

- - Average (Maya: AveragePolygonNormals)
- - Conform (Maya: ConformPolygonNormals)
- ✓ `reverse` Reverse (Maya: ReversePolygonNormals)
- - Set to Face (Maya: SetToFaceNormals)
- - Set Vertex Normal (Maya: SetVertexNormal)
- ✓ `hardEdge` Harden Edge (Maya: PolygonHardenEdge)
- ✓ `softEdge` Soften Edge (Maya: PolygonSoftenEdge)
- ✓ `softHard` Soften/Harden Edges (Maya: PolygonSoftenHarden)
- - Lock Normals (Maya: LockNormals)
- - Unlock Normals (Maya: UnlockNormals)
- - Vertex Normal Edit Tool (Maya: PolygonNormalEditTool)
- - Apply Color (Maya: PolygonApplyColor)
- - Paint Vertex Color Tool (Maya: PaintVertexColorTool)
- - Create Empty Set (Maya: CreateEmptySet)
- - Delete Current Set (Maya: DeleteCurrentSet)
- - Rename Current Set... (Maya: RenameCurrentSet)
- - Modify Current Set (Maya: ModifyCurrentSet)
- - Set Keyframe for Vertex Color (Maya: SetKeyframeForVertexColor)
- - Color Set Editor (Maya: OpenColorSetEditor)
- - Prelight (Maya) (Maya: PreflightPolygon)
- - Assign New Set (Maya: AssignNewSet)
- - Edit Assigned Set (Maya: EditAssignedSet)
- - Toggle Display Colors Attribute (Maya: ToggleDisplayColorsAttr)
- - Color Material Channel > None (Maya: SetCMCNone)
- - Color Material Channel > Ambient (Maya: SetCMCAmbient)
- - Color Material Channel > Ambient+Diffuse (Maya: SetCMCAmbientDiffuse)
- - Color Material Channel > Diffuse (Maya: SetCMCDiffuse)
- - Color Material Channel > Specular (Maya: SetCMCSpecular)
- - Color Material Channel > Emission (Maya: SetCMCEmission)
- - Material Blend Setting > Overwrite (Maya: SetMBSOverwrite)
- - Material Blend Setting > Add (Maya: SetMBSAdd)
- - Material Blend Setting > Subtract (Maya: SetMBSSubtract)
- - Material Blend Setting > Multiply (Maya: SetMBSMultiply)
- - Material Blend Setting > Divide (Maya: SetMBSDivide)
- - Material Blend Setting > Average (Maya: SetMBSAverage)
- - Material Blend Setting > Modulate 2x (Maya: SetMBSModulate2)
- - Per Instance Sharing > Select Shared Instances (Maya: SelectSharedColorInstances)
- - Per Instance Sharing > Share Instances (Maya: ShareColorInstances)

### Curves

- - Lock Length (Maya: LockCurveLength)
- - Unlock Length (Maya: UnlockCurveLength)
- - Bend (Maya: BendCurves)
- - Curl (Maya: CurlCurves)
- - Scale Curvature (Maya: ScaleCurvature)
- - Smooth (Maya: SmoothHairCurves)
- - Straighten (Maya: StraightenCurves)
- - Duplicate Surface Curves (Maya: DuplicateCurve)
- - Align (Maya: AlignCurve)
- - Add Points Tool (Maya: AddPointsTool)
- - Attach (Maya: AttachCurve)
- - Detach (Maya: DetachCurve)
- - Edit Curve Tool (Maya: CurveEditTool)
- - Move Seam (Maya: MoveCurveSeam)
- - Open/Close (Maya: OpenCloseCurve)
- - Fillet (Maya: CurveFillet)
- - Cut (Maya: CutCurve)
- - Intersect (Maya: IntersectCurve)
- - Extend > Extend Curve (Maya: ExtendCurve)
- - Extend > Extend Curve On Surface (Maya: ExtendCurveOnSurface)
- - Insert Knot (Maya: InsertKnot)
- - Offset > Offset Curve (Maya: OffsetCurve)
- - Offset > Offset Curve On Surface (Maya: OffsetCurveOnSurface)
- - CV Hardness (Maya: CVHardness)
- - Fit B-spline (Maya: FitBSpline)
- - Project Tangent (Maya: ProjectTangent)
- - Smooth (Maya: SmoothCurve)
- - Bezier Curves > Anchor Presets > Bezier (Maya: BezierPresetBezier)
- - Bezier Curves > Anchor Presets > Bezier Corner (Maya: BezierPresetBezierCorner)
- - Bezier Curves > Anchor Presets > Corner (Maya: BezierPresetCorner)
- - Bezier Curves > Tangent Options > Smooth Anchor Tangents (Maya: BezierSetAnchorSmooth)
- - Bezier Curves > Tangent Options > Break Anchor Tangents (Maya: BezierSetAnchorBroken)
- - Bezier Curves > Tangent Options > Even Anchor Tangents (Maya: BezierSetAnchorEven)
- - Bezier Curves > Tangent Options > Uneven Anchor Tangents (Maya: BezierSetAnchorUneven)
- - Rebuild (Maya: RebuildCurve)
- - Reverse Direction (Maya: ReverseCurve)

### Surfaces

- - Loft (Maya: Loft)
- - Planar (Maya: Planar)
- - Revolve (Maya: Revolve)
- - Birail > Birail 1 Tool (Maya: Birail1)
- - Birail > Birail 2 Tool (Maya: Birail2)
- - Birail > Birail 3+ Tool (Maya: Birail3)
- - Extrude (Maya: Extrude)
- - Boundary (Maya: Boundary)
- - Square (Maya: SquareSurface)
- - Bevel (Maya: Bevel)
- - Bevel Plus (Maya: BevelPlus)
- - Duplicate NURBS Patch (Maya: DuplicateNURBSPatches)
- - Align (Maya: AlignSurfaces)
- - Attach (Maya: AttachSurfaces)
- - Attach Without Moving (Maya: AttachSurfaceWithoutMoving)
- - Detach (Maya: DetachSurfaces)
- - Move Seam (Maya: MoveSurfaceSeam)
- - Open/Close (Maya: OpenCloseSurfaces)
- - Intersect (Maya: IntersectSurfaces)
- - Project Curve on Surface (Maya: ProjectCurveOnSurface)
- - Trim Tool (Maya: TrimTool)
- - Untrim (Maya: UntrimSurfaces)
- - Extend (Maya: ExtendSurfaces)
- - Insert Isoparms (Maya: InsertIsoparms)
- - Offset (Maya: OffsetSurfaces)
- - Round Tool (Maya: RoundTool)
- - Stitch > Stitch Surface Points (Maya: StitchSurfacePoints)
- - Stitch > Stitch Edges Tool (Maya: StitchEdgesTool)
- - Stitch > Global Stitch (Maya: GlobalStitch)
- - Surface Fillet > Circular Fillet (Maya: CircularFillet)
- - Surface Fillet > Freeform Fillet (Maya: FreeformFillet)
- - Surface Fillet > Fillet Blend Tool (Maya: FilletBlendTool)
- - Sculpt Geometry Tool (Maya: SculptGeometryTool)
- - Surface Editing > Surface Editing Tool (Maya: SurfaceEditingTool)
- - Surface Editing > Break Tangent (Maya: BreakTangent)
- - Surface Editing > Smooth Tangent (Maya: SmoothTangent)
- - Booleans > Union Tool (Maya: SurfaceBooleanUnionTool)
- - Booleans > Difference Tool (Maya: SurfaceBooleanSubtractTool)
- - Booleans > Intersection Tool (Maya: SurfaceBooleanIntersectTool)
- - Rebuild (Maya: RebuildSurfaces)
- - Reverse Direction (Maya: ReverseSurfaceDirection)

### Deform

- - Curve Warp (Maya: CurveWarp)
- - Blend Shape (Maya: CreateBlendShape)
- - Cluster (Maya: CreateCluster)
- - Curve Warp (Maya: CurveWarp)
- - Delta Mush (Maya: DeltaMush)
- - ML Deformer (Maya: MLDeformer)
- - Tension (Maya: Tension)
- - Solidify (Maya: Solidify)
- - Lattice (Maya: CreateLattice)
- - Proximity Wrap (Maya: ProximityWrap)
- - Wrap (Maya: CreateWrap)
- - ShrinkWrap (Maya: CreateShrinkWrap)
- - Morph (Maya: Morph)
- - Wire (Maya: WireTool)
- - Wrinkle (Maya: WrinkleTool)
- - Pose Space Deformation > Create Pose Interpolator (Maya: CreatePoseInterpolator)
- - Pose Space Deformation > PoseEditor (Maya: PoseEditor)
- - Nonlinear > Bend (Maya: Bend)
- - Nonlinear > Flare (Maya: Flare)
- - Nonlinear > Sine (Maya: Sine)
- - Nonlinear > Squash (Maya: Squash)
- - Nonlinear > Twist (Maya: Twist)
- - Nonlinear > Wave (Maya: Wave)
- - Soft Modification Tool (Maya: SoftModTool)
- - Sculpt (Maya: CreateSculptDeformer)
- - Texture (Maya: CreateTextureDeformer)
- - Jiggle > Jiggle Deformer (Maya: CreateJiggleDeformer)
- - Jiggle > Jiggle Disk Cache (Maya: CreateDiskCache)
- - Jiggle > Jiggle Disk Cache Attributes (Maya: GlobalDiskCacheControl)
- - Point On Curve (Maya: PointOnCurve)
- - Add Tweak (Maya: AddTweak)
- - Blend Shape > Add (Maya: AddBlendShape)
- - Blend Shape > Remove (Maya: RemoveBlendShape)
- - Blend Shape > Swap (Maya: SwapBlendShape)
- - Blend Shape > Bake Topology To Targets (Maya: BakeTopologyToTargets)
- - Blend Shape > Edit Normalization Groups (Maya: EditNormalizationGroups)
- - Lattice > Remove Lattice Tweaks (Maya: RemoveLatticeTweaks)
- - Lattice > Reset Lattice (Maya: ResetLattice)
- - Wrap > Add Influence (Maya: AddWrapInfluence)
- - Wrap > Remove Influence (Maya: RemoveWrapInfluence)
- - ShrinkWrap > Add surfaces (Maya: AddShrinkWrapSurfaces)
- - ShrinkWrap > Remove Inner Object (Maya: RemoveShrinkWrapInnerObject)
- - ShrinkWrap > Remove surfaces (Maya: RemoveShrinkWrapSurfaces)
- - ShrinkWrap > Remove Target (Maya: RemoveShrinkWrapTarget)
- - ShrinkWrap > Set Inner Object (Maya: SetShrinkWrapInnerObject)
- - ShrinkWrap > Set Target (Maya: SetShrinkWrapTarget)
- - Wire > Add (Maya: AddWire)
- - Wire > Add Holder (Maya: AddHolder)
- - Wire > Parent Base Wire (Maya: ParentBaseWire)
- - Wire > Remove (Maya: RemoveWire)
- - Wire > Reset (Maya: ResetWire)
- - Wire > Show Base Wire (Maya: ShowBaseWire)
- - Wire > Wire Dropoff Locator (Maya: WireDropoffLocator)
- - Display Intermediate Objects (Maya: DisplayIntermediateObjects)
- - Hide Intermediate Objects (Maya: HideIntermediateObjects)
- - Paint Weights > Blend Shape (Maya: ArtPaintBlendShapeWeightsTool)
- - Paint Weights > Cluster (Maya: PaintClusterWeightsTool)
- - Paint Weights > Delta Mush (Maya: PaintDeltaMushWeightsTool)
- - Paint Weights > Tension (Maya: PaintTensionWeightsTool)
- - Paint Weights > Proximity Wrap (Maya: PaintProximityWrapWeightsTool)
- - Paint Weights > Lattice (Maya: PaintLatticeWeightsTool)
- - Paint Weights > ShrinkWrap (Maya: PaintShrinkWrapWeightsTool)
- - Paint Weights > Wire (Maya: PaintWireWeightsTool)
- - Paint Weights > Nonlinear (Maya: PaintNonlinearWeightsTool)
- - Paint Weights > Jiggle (Maya: PaintJiggleWeightsTool)
- - Paint Weights > Texture Deformer (Maya: PaintTextureDeformerWeightsTool)
- - Mirror Deformer Weights (Maya: MirrorDeformerWeights)
- - Export Weights... (Maya: ExportDeformerWeights)
- - Import Weights... (Maya: ImportDeformerWeights)
- - Edit Membership Tool (Maya: EditMembershipTool)
- - Prune Membership > Cluster (Maya: PruneCluster)
- - Prune Membership > Lattice (Maya: PruneLattice)
- - Prune Membership > Sculpt (Maya: PruneSculpt)
- - Prune Membership > Wire (Maya: PruneWire)
- - Paint Membership (Maya: PaintSetMembershipTool)

### UV

- ✓ `uvEditor` UV Editor (Maya: TextureViewWindow)
- - UV Set Editor (Maya: UVSetEditor)
- ✓ `uvChecker` Assign Checker Shader (Maya: TogglePolyUVsCreateShader)
- ✓ `uvAutomatic` Automatic (Maya: UVAutomaticProjection)
- - Best Plane (Maya: BestPlaneTexturingTool)
- ✓ `uvCamera` Camera-based (Maya: UVCameraBasedProjection)
- - Contour Stretch (Maya: UVContourStretchProjection)
- - Normal-Based (Maya: UVNormalBasedProjection)
- ✓ `uvCylindrical` Cylindrical (Maya: UVCylindricProjection)
- ✓ `uvPlanar` Planar (Maya: UVPlanarProjection)
- ✓ `uvSpherical` Spherical (Maya: UVSphericalProjection)
- ✓ `uvAutoSeams` Auto Seams (Maya: AutoSeamUVs)
- ✓ `uvCut` Cut UV Edges (Maya: CutUVsWithoutHotkey)
- ✓ `uvSew` Sew UV Edges (Maya: SewUVsWithoutHotkey)
- - Split UVs (Maya: SplitUV)
- - Delete UVs (Maya: DeleteUVsWithoutHotkey)
- - Merge UVs (Maya: MergeUV)
- - 3D Cut and Sew UV Tool (Maya: SetCutSewUVTool)
- - 3D Grab UV Tool (Maya: SetMeshGrabUVTool)

### Key

- ✓ `setKey` Set Key (Maya: SetKey)
- - Set Key on Animated (Maya: SetKeyAnimated)
- - Set Key on Translate (Maya: SetKeyTranslate)
- - Set Key on Rotate (Maya: SetKeyRotate)
- - Set Key on Scale (Maya: SetKeyScale)
- - Set Breakdown Key (Maya: SetBreakdownKey)
- - Set Driven Key > Set... (Maya: SetDrivenKey)
- - Set Driven Key > Go to Previous (Maya: GoToPreviousDrivenKey)
- - Set Driven Key > Go to Next (Maya: GoToNextDrivenKey)
- - Set Blend Shape Target Weight Keys (Maya: KeyBlendShapeTargetsWeight)
- - Insert Key (Maya: InsertKey)
- - Insert Key on Translate (Maya: InsertKeyTranslate)
- - Insert Key on Rotate (Maya: InsertKeyRotate)
- - Insert Key on Scale (Maya: InsertKeyScale)
- - Cut Keys (Maya: CutKeys)
- ✓ `copyAnim` Copy Keys (Maya: CopyKeys)
- ✓ `pasteAnim` Paste Keys (Maya: PasteKeys)
- ✓ `deleteKey` Delete Keys (Maya: DeleteKeys)
- - $cmd (Maya: $cmd)
- - Hold Current Keys (Maya: HoldCurrentKeys)
- - IK/FK Keys > Set IK/FK Key (Maya: SetIKFKKeyframe)
- - IK/FK Keys > Enable IK Solver (Maya: ToggleFkIk)
- - IK/FK Keys > Connect to IK/FK (Maya: ConnectNodeToIKFK)
- - IK/FK Keys > Move IK to FK (Maya: MoveIKtoFK)
- - Create Character Set (Maya: CreateCharacter)
- - Create Subcharacter Set (Maya: CreateSubCharacter)
- - Character Mapper (Maya: CharacterMapper)
- - EditCharacterAttributes (Maya: EditCharacterAttributes)
- - Add to Character Set (Maya: AddToCharacterSet)
- - Remove from Character Set (Maya: RemoveFromCharacterSet)
- - Merge Character Sets (Maya: MergeCharacterSet)
- - Redirect (Maya: AddAnimationOffset)
- - Scene Time Warp > Add Scene Time Warp (Maya: AddTimeWarp)
- - Scene Time Warp > Select Scene Time Warp (Maya: SelectTimeWarp)
- - Scene Time Warp > Delete Scene Time Warp (Maya: DeleteTimeWarp)
- - Scene Time Warp > Enable Scene Time Warp (Maya: EnableTimeWarp)

### Playback

- - Playblast (Maya: PlayblastWindow)
- ✓ `playPause` Play (Maya: PlaybackForward)
- - Backward (Maya: PlaybackBackward)
- - Stop (Maya: PlaybackStop)
- ✓ `nextKey` Next Key (Maya: NextKey)
- ✓ `prevKey` Prev Key (Maya: PreviousKey)
- - Select Next Key (Maya: SelectNextKey)
- - Select Previous Key (Maya: SelectPreviousKey)
- - Next Frame (Maya: NextFrame)
- - Prev Frame (Maya: PreviousFrame)
- ✓ `rangeStart` Play Range Start (Maya: GoToMinFrame)
- ✓ `rangeEnd` Play Range End (Maya: GoToMaxFrame)
- - Set Range to > Enabled Clips (Maya: PlaybackRangeEnabledClips)
- - Set Range to > Min/Max (Maya: PlaybackRangeMinMax)
- - Set Range to > Preferences (Maya: PlaybackRangePrefs)
- - Set Range to > Selected (Maya: PlaybackRangeHighlight)
- - Set Range to > Sound Length (Maya: PlaybackRangeSound)
- - Set Range to > Start/End (Maya: PlaybackRangeStartEnd)
- - Playback Speed > Play Every Frame, Free (Maya: PlaybackFree)
- - Playback Speed > Play Every Frame, Max Real-time (Maya: PlaybackPefRealtime)
- - Playback Speed > Real-time (Maya: PlaybackRealtime)
- - Playback Looping > Continuous (Maya: PlaybackLoopContinuous)
- - Playback Looping > Once (Maya: PlaybackLoopOnce)
- - Playback Looping > Oscillate (Maya: PlaybackLoopOscillate)
- - Enable Stepped Preview (Maya: PlaybackSteppedPreview)
- - Render Current Frame (Maya: RenderIntoNewWindow)
- - RenderGlobalsWindow (Maya: RenderGlobalsWindow)

### Shift+RMB object

- ✓ `extrude` (S) Mesh tools > Extrude
- ✓ `insertLoopTool` (SW) Mesh tools > Insert Edge Loop Tool
- ✓ `fillHole` (NE) Mesh tools > Fill Holes
- ✓ `targetWeld` (N) Mesh tools > Target Weld Tool
- ✓ `multiCut` (W) Mesh tools > Multi-Cut
- ✓ `sculpt` (NW) Mesh tools > Sculpt Tool
- ✓ `softHardDisplay` (S) Soften/Harden Edges > Toggle Soft Edge Display
- ✓ `hardEdge` (SE) Soften/Harden Edges > Harden Edge
- ✓ `softHard` (E) Soften/Harden Edges > Soften/Harden
- ✓ `softEdge` (NE) Soften/Harden Edges > Soften Edge
- - Smart Bevel (Maya: PolySmartBevel)
- ✓ `offsetEdgeLoop` Offset Edge Loop (Maya: DuplicateEdges)
- ✓ `smooth` Smooth (Maya: SmoothPolygon)
- - Unsmooth (Maya: UnsmoothPolygon)
- - Subdiv Proxy (Maya: SmoothProxy)
- - Crease Tool (Maya: PolyCreaseTool)
- - Project Curve on mesh (Maya: ProjectCurveOnMesh)
- - Split mesh with projected curve (Maya: SplitMeshWithProjectedCurve)
- ✓ `mirror` Mirror (Maya: MirrorPolygonGeometry)
- ✓ `triangulate` Triangulate (Maya: Triangulate)
- ✓ `quadrangulate` Quadrangulate (Maya: Quadrangulate)
- ✓ `sculptReduce` Reduce (Maya: ReducePolygon)
- ✓ `sculptRemesh` Remesh (Maya: PolyRemesh)
- ✓ `sculptQuadRemesh` Retopologize (Maya: PolyRetopo)
- - Transfer Vertex Order (Maya: TransferVertexOrder)
- ✓ `separate` Separate (Maya: SeparatePolygon)
- ✓ `combine` Combine (Maya: CombinePolygons)
- ✓ `boolUnion` Booleans > Union (Maya: PolygonBooleanUnion)
- ✓ `boolDifference` Booleans > Difference (A - B) (Maya: PolygonBooleanDifference)
- ✓ `boolDifferenceBA` Booleans > Difference (B - A) (Maya: PolygonBooleanDifferenceBA)
- ✓ `boolIntersection` Booleans > Intersection (Maya: PolygonBooleanIntersection)
- - Booleans > Slice (Maya: PolygonBooleanSlice)
- - Booleans > Hole Punch (Maya: PolygonBooleanHolePunch)
- - Booleans > Cut Out (Maya: PolygonBooleanCutOut)
- - Booleans > Split Edges (Maya: PolygonBooleanSplitEdges)
- - Cleanup... (Maya: CleanupPolygonOptions)
- - Connect Tool (Maya: dR_connectTool)
- ✓ `quadDraw` Quad Draw Tool (Maya: dR_quadDrawTool)
- ✓ `backfaces` Polygon Display > Toggle Backface Culling
- - Polygon Display > Toggle Border Edges
- - Polygon Display > Toggle Texture Border Edges
- - Polygon Display > Toggle Face Normals
- - Polygon Display > Toggle Vertex Normals
- - Polygon Display > Toggle Face Centers (Maya: TogglePolygonFaceCenters)
- - Polygon Display > Toggle Hidden Triangles
- - Polygon Display > Toggle Vertices
- - Polygon Display > Reset Polygon Display

### Shift+RMB vertex

- ✓ `extrude` (S) Vertex tools > Extrude Vertex
- ✓ `chamfer` (E) Vertex tools > Chamfer Vertex
- ✓ `deleteEdgeVert` (SW) Vertex tools > Delete Vertex
- ✓ `vertexNormals` (S) Vertex Normals > Toggle Vertex Normal Display
- - (NE) Vertex Normals > Average Normals
- - (E) Vertex Normals > Vertex Normal Edit Tool
- - (SE) Vertex Normals > Set Normals to Face
- ✓ `merge` (NE) Merge Vertices > Merge Vertices
- ✓ `mergeCenter` (N) Merge Vertices > Merge Vertices To Center
- ✓ `targetWeld` (S) Merge Vertices > Target Weld Tool
- ✓ `averageVerts` (NE) Vertex tools > Average Vertices
- ✓ `multiCut` (W) Vertex tools > Multi-Cut
- ✓ `paintSelect` (NW) Vertex tools > Paint Select Vertices
- - Crease Tool (Maya: PolyCreaseTool)
- ✓ `connect` Connect Components (Maya: ConnectComponents)
- ✓ `detach` Detach Components (Maya: DetachComponent)
- - Transform Component
- - Connect Tool (Maya: dR_connectTool)
- ✓ `circularize` Circularize Vertices (Maya: PolyCircularize)
- - Reorder Vertices (Maya: ReorderVertex)
- - Apply Color (Maya: PolygonApplyColor)
- ✓ `backfaces` Polygon Display > Toggle Backface Culling
- - Polygon Display > Toggle Vertices
- - Polygon Display > Toggle Vertex Normals
- - Polygon Display > Toggle Vertex Numbers
- - Polygon Display > Reset Polygon Display

### Shift+RMB edge

- ✓ `extrude` (S) Edge tools > Extrude Edge
- ✓ `deleteEdgeVert` (SW) Edge tools > Delete Edge
- ✓ `bevel` (E) Edge tools > Bevel Edge
- ✓ `softHardDisplay` (S) Soften/Harden Edges > Toggle Soft Edge Display
- ✓ `hardEdge` (SE) Soften/Harden Edges > Harden Edge
- ✓ `softHard` (E) Soften/Harden Edges > Soften/Harden
- ✓ `softEdge` (NE) Soften/Harden Edges > Soften Edge
- ✓ `merge` (NE) Merge/Collapse Edges > Merge Border Edges
- ✓ `targetWeld` (S) Merge/Collapse Edges > Target Weld Tool
- - (NW) Merge/Collapse Edges > Merge Edge Tool
- ✓ `collapse` (E) Merge/Collapse Edges > Collapse Edge
- ✓ `mergeCenter` (N) Merge/Collapse Edges > Merge Edges To Center
- ✓ `flipTriangleEdge` (N) Flip/Spin Edge > Flip Triangle Edge
- ✓ `spinEdge` (E) Flip/Spin Edge > Spin Forward
- ✓ `spinEdgeBack` (W) Flip/Spin Edge > Spin Backward
- ✓ `multiCut` (W) Edge tools > Multi-Cut
- ✓ `paintSelect` (NW) Edge tools > Paint Select Edges
- - Smart Bevel (Maya: PolySmartBevel)
- - Crease Tool (Maya: PolyCreaseTool)
- ✓ `offsetEdgeLoop` Offset Edge Loop (Maya: DuplicateEdges)
- ✓ `insertLoopTool` Insert Edge Loop Tool (Maya: SplitEdgeRingTool)
- ✓ `slideEdge` Slide Edge Tool (Maya: SlideEdgeTool)
- ✓ `circularize` Circularize Components (Maya: PolyCircularize)
- - Edit Edge Flow (Maya: PolyEditEdgeFlow)
- - Add Divisions To Edge
- ✓ `bridge` Bridge (Maya: performBridgeOrFill)
- ✓ `fillHole` Fill Hole (Maya: FillHole)
- ✓ `connect` Connect Components (Maya: ConnectComponents)
- ✓ `detach` Detach Components (Maya: DetachComponent)
- - Transform Component
- - Connect Tool (Maya: dR_connectTool)
- ✓ `backfaces` Polygon Display > Toggle Backface Culling
- - Polygon Display > Toggle Border Edges
- - Polygon Display > Toggle Texture Border Edges
- - Polygon Display > Toggle Hidden Triangle Edges
- ✓ `softHardDisplay` Polygon Display > Toggle Soft Edge Display
- - Polygon Display > Reset Polygon Display

### Shift+RMB face

- ✓ `mergeCenter` (N) Face tools > Merge Faces To Center
- ✓ `extrude` (S) Face tools > Extrude Face
- ✓ `wedge` (SW) Face tools > Wedge Face
- ✓ `poke` (NE) Face tools > Poke Face
- ✓ `bevel` (E) Face tools > Bevel Face
- ✓ `faceNormals` (S) Face Normals > Toggle Face Normal Display
- - (NE) Face Normals > Reverse Propagate
- - (SE) Face Normals > Conform Normals
- ✓ `reverse` (E) Face Normals > Reverse Normals
- ✓ `multiCut` (W) Face tools > Multi-Cut
- ✓ `paintSelect` (NW) Face tools > Paint Select Faces
- - Smart Extrude (Maya: SmartExtrude)
- - Smart Bevel (Maya: PolySmartBevel)
- ✓ `smooth` Smooth Faces
- - Assign Invisible Faces (Maya: PolyAssignSubdivHole)
- ✓ `addDivisions` Add Divisions To Faces (Maya: SubdividePolygon)
- ✓ `circularize` Circularize Components (Maya: PolyCircularize)
- ✓ `connect` Connect Components (Maya: ConnectComponents)
- ✓ `detach` Detach Components (Maya: DetachComponent)
- ✓ `triangulate` Triangulate Faces (Maya: Triangulate)
- ✓ `quadrangulate` Quadrangulate Faces (Maya: Quadrangulate)
- ✓ `sculptReduce` Reduce Faces (Maya: ReducePolygon)
- ✓ `sculptRemesh` Remesh (Maya: PolyRemesh)
- ✓ `bridge` Bridge Faces (Maya: BridgeEdge)
- ✓ `mirror` Mirror (Maya: MirrorPolygonGeometry)
- ✓ `extractFace` Extract Faces (Maya: ExtractFace)
- ✓ `duplicateFace` Duplicate Face (Maya: DuplicateFace)
- - Transform Component
- - Connect Tool (Maya: dR_connectTool)
- ✓ `targetWeld` Target Weld Tool (Maya: dR_targetWeldTool)
- ✓ `backfaces` Polygon Display > Toggle Backface Culling
- - Polygon Display > Toggle Face Centers (Maya: TogglePolygonFaceCenters)
- - Polygon Display > Toggle Face Normals
- - Polygon Display > Toggle Face Numbers
- - Polygon Display > Toggle Hidden Triangles
- - Polygon Display > Reset Polygon Display

### Shift+RMB default

- - (NE) Create > Disc
- ✓ `sphere` (E) Create > Sphere
- ✓ `torus` (SE) Create > Torus
- ✓ `cube` (S) Create > Cube
- ✓ `cone` (SW) Create > Cone
- ✓ `cylinder` (W) Create > Cylinder
- ✓ `plane` (NW) Create > Plane
- - Platonic Solid (Maya: CreatePolygonPlatonic)
- - Pyramid (Maya: CreatePolygonPyramid)
- - Prism (Maya: CreatePolygonPrism)
- - Pipe (Maya: CreatePolygonPipe)
- - Helix (Maya: CreatePolygonHelix)
- - Gear (Maya: CreatePolygonGear)
- - Soccer Ball (Maya: CreatePolygonSoccerBall)
- - Super Ellipse (Maya: CreatePolygonSuperEllipse)
- - Spherical Harmonics (Maya: CreatePolygonSphericalHarmonics)
- - Ultra Shape (Maya: CreatePolygonUltraShape)
- - Type (Maya: CreatePolygonType)
- - SVG (Maya: CreatePolygonSVG)
- ✓ `quadDraw` Quad Draw Tool (Maya: dR_quadDrawTool)
- - Interactive Creation (Maya: toggleCreatePolyPrimitiveAsTool)
- - Exit On Completion (Maya: togglePolyPrimitiveAsToolExitOnComplete)
- - Polygon Display All > Backface Culling on for All Polys
- - Polygon Display All > Backface Culling off for All Polys
- - Polygon Display All > Toggle All Geometry Border Edges
- - Polygon Display All > Toggle All Texture Border Edges
- - Polygon Display All > Toggle All Face Normals
- - Polygon Display All > Toggle All Vertex Normals
- - Polygon Display All > Toggle All Face Centers
- - Polygon Display All > Toggle All Hidden Triangles
- - Polygon Display All > Toggle All Vertices
- - Polygon Display All > Reset Display for All Polys

### zones

- ✓ `persp` (N) Perspective View
- ✓ `side` (E) Side View
- ✓ `front` (S) Front View
- ✓ `top` (W) Top View
- - (NW) Left View
- - (SW) Back View
- - (SE) Bottom View
- - Hotbox Style > Zones and Menu Rows
- - Hotbox Style > Zones Only
- - Hotbox Style > Center Zone Only
- ✓ `single` (N) Single Perspective
- - (NE) Hypershade/Render/Persp
- - (SE) Hypershade/Outliner/Persp
- - (E) Hypershade/Persp
- ✓ `winOutliner` (S) Toggle Outliner
- - (SW) Persp/Graph/Outliner
- - (W) Persp/Graph
- - (NW) Persp/Relationship Editor
- ✓ `winOutliner` (N) Outliner
- ✓ `graphEditor` (E) Graph Editor
- - (SE) Dope Sheet
- - (S) Hypergraph
- - (SW) Node Editor
- ✓ `winMaterials` (W) Hypershade
- ✓ `renderDialog` (NW) Render View
- - (NE) Set Editor
- - (N) Help Line
- - (NE) Status Line
- ✓ `winChannel` (E) Attributes > Channel Box
- ✓ `layerEditor` (S) Attributes > Layer Editor
- - (W) Attributes > Attribute Editor
- - (N) Attributes > Tool Settings
- - (SE) Tool Box
- - (S) Time Slider
- - (SW) Range Slider
- ✓ `winShelf` (W) Shelf
- - (NW) Command Line
- - (N) NURBS Mask
- ✓ `hierarchy` (NE) Hierarchy
- - (E) Animation Mask
- - (SE) Deformations Mask
- - (S) Dynamics Mask
- - (SW) Polygons Mask
- - (W) Rendering Mask
- ✓ `objComp` (NW) Object/Components

