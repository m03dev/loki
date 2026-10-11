extends SceneTree

var _dock: Control
var _t: float = 0.0
var _opened: bool = false
var _done: bool = false

func _initialize() -> void:
	var script: Script = load("res://addons/loki/loki_dock.gd")
	_dock = script.new() as Control
	root.add_child(_dock)

func _process(delta: float) -> bool:
	_t += delta
	if not _opened and _t >= 12.0:
		_opened = true
		_dock.call("_open_ecc")
	if _done or _t < 18.0:
		return false
	_done = true
	var tabs: TabBar = _dock.get("_tabs") as TabBar
	var agents_list: ItemList = _dock.get("_ecc_agents_list")
	var skills_list: ItemList = _dock.get("_ecc_skills_list")
	print("PROBE ready=", _dock.get("_bridge_ready"),
		" tabs=", tabs.get_tab_count(),
		" ecc_dialog=", _dock.get("_ecc_dialog") != null,
		" agents=", (_dock.get("_ecc_agents") as Array).size(),
		" skills=", (_dock.get("_ecc_skills") as Array).size(),
		" agents_rows=", (agents_list.item_count if agents_list != null else -1),
		" skills_rows=", (skills_list.item_count if skills_list != null else -1))
	return true
