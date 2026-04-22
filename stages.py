import glob
import glob
import json
import uuid
from datetime import timedelta
from enum import Enum
from pathlib import Path

import qtawesome as qta
import sqlalchemy
from PySide6.QtCore import Qt, QCoreApplication
from PySide6.QtWidgets import QWidget, QFormLayout, QRadioButton, QMessageBox, QFileDialog, \
    QListWidget, QVBoxLayout, QListWidgetItem, QLabel, QInputDialog, QHBoxLayout
from dateutil.parser import parser
from jinja2 import FileSystemLoader, select_autoescape, Environment
from sqlalchemy import Select, create_engine
from sqlalchemy.orm import Session

import api
import plugin
import results
from models import Category
from plugin import Plugin
from ui.qtaiconbutton import QTAIconButton


class StagesPlugin(Plugin):
    name = "StageHelper"
    author = "JJ"
    version = "1.1.1"

    def __init__(self, mw):
        super().__init__(mw)
        self.stage_helper = StagesHelperWindow(mw)
        self.register_mw_tab(self.stage_helper, qta.icon("mdi6.calendar-blank-multiple"))
        self.register_report(plugin.ReportType.RESULTS, "Celkové výsledky etapového závodu",
                             "Vypočítá celkové výsledky etapového závodu", "StagesHelper", self.stage_helper.calculate,
                             {})

    def on_readout(self, sinum: int):
        pass

    def on_startup(self):
        pass

    def on_menu(self):
        pass


def _create_folder():
    rootdir = Path.home() / ".ardfevent" / "stages"

    if not rootdir.exists():
        rootdir.mkdir()


class StageClickMode(Enum):
    NONE = 0
    DELETE = 1


class StagesHelperWindow(QWidget):
    def __init__(self, mw):
        super().__init__()

        self.mode = StageClickMode.NONE
        self.file = None

        self.mw = mw
        self.pw = None

        self.setWindowTitle("Etapový závod")

        lay = QVBoxLayout()
        self.setLayout(lay)

        self.name_lbl = QLabel()
        lay.addWidget(self.name_lbl)

        btn_lay = QHBoxLayout()
        lay.addLayout(btn_lay)

        self.new_btn = QTAIconButton("mdi6.plus", "Nový etapový závod")
        self.new_btn.clicked.connect(self._new_file)
        btn_lay.addWidget(self.new_btn)

        self.add_btn = QTAIconButton("mdi6.calendar-plus-outline", "Přidat etapu")
        self.add_btn.clicked.connect(self._add_stage)
        btn_lay.addWidget(self.add_btn)

        self.del_btn = QTAIconButton("mdi6.trash-can-outline", "Smazat etapu (klik)")
        self.del_btn.clicked.connect(self._delete_enable)
        btn_lay.addWidget(self.del_btn)

        self.stages_list = QListWidget()
        self.stages_list.itemClicked.connect(self._stage_clicked)
        lay.addWidget(self.stages_list)

        form_lay = QFormLayout()
        lay.addLayout(form_lay)

        self.timetx_radio = QRadioButton("Součet kontrol, příp. časů")
        form_lay.addRow(self.timetx_radio)

        self.basic_radio = QRadioButton("Prostý součet umístění")
        form_lay.addRow(self.basic_radio)

    def _show(self):
        self.stages_list.clear()
        _create_folder()

        if fileuuid := api.get_basic_info(self.mw.db).get("stages_uuid"):
            for file in glob.glob((Path.home() / ".ardfevent" / "stages" / "*.json").as_posix()):
                with open(file, "r") as f:
                    try:
                        if contents := json.load(f)["stages"]:
                            f = next((f for f in contents if (f["uuid"] == fileuuid or f["url"] == self.mw.db.url)),
                                     None)
                            if f:
                                self._open_file(file)
                            self.stages_list.setEnabled(True)
                            self.basic_radio.setEnabled(True)
                            self.timetx_radio.setEnabled(True)
                            self.add_btn.setEnabled(True)
                            self.del_btn.setEnabled(True)
                            return
                    except:
                        pass
        else:
            api.set_basic_info(self.mw.db, {"stages_uuid": uuid.uuid4().hex})
        self.stages_list.setEnabled(False)
        self.basic_radio.setEnabled(False)
        self.timetx_radio.setEnabled(False)
        self.add_btn.setEnabled(False)
        self.del_btn.setEnabled(False)
        self.name_lbl.setText("Nejdříve založte etapový závod")

    def _open_file(self, fp: str):
        with open(fp, "r") as f:
            try:
                data = json.load(f)
                match data["mode"]:
                    case 0:
                        self.timetx_radio.click()
                    case 1:
                        self.basic_radio.click()
                    case _:
                        pass

                stages = []
                for stage in data["stages"]:
                    eng = create_engine(stage["url"])
                    bi = api.get_basic_info(eng)
                    stages.append((bi["name"], parser().parse(bi["date_tzero"]), stage["url"]))

                stages.sort(key=lambda x: x[0:2][::-1])

                self.stages_list.clear()

                for stage in stages:
                    item = QListWidgetItem(f"{stage[1].strftime("%d. %m. %Y %H:%M")} - {stage[0]}")
                    item.setData(Qt.UserRole, stage[2])
                    self.stages_list.addItem(item)

                self.name_lbl.setText(f"ID etapového závodu: {Path(fp).stem}")

                self.file = fp

            except:
                pass

    def _add_stage(self):
        if dbfile := \
                QFileDialog.getOpenFileName(self, QCoreApplication.translate("MainWindow", "Otevřít závod"), "",
                                            "ARDFEvent databáze (*.ardf);;ARDFEvent databáze - pre 1.1 (*.sqlite);;Všechny soubory (*)")[
                    0]:
            it = QListWidgetItem("")
            it.setData(Qt.UserRole, f"sqlite:///{dbfile}")
            self.stages_list.addItem(it)
            self._save()
            self._show()
        else:
            return

    def _new_file(self):
        fid, ok = QInputDialog.getText(
            self,
            "Nový etapový závod",
            "Zadejte ID (jméno souboru) etapového závodu (např. PP_2025):",
        )
        fp = Path.home() / ".ardfevent" / "stages" / f"{fid}.json"
        if fp.exists():
            QMessageBox.critical(self, "Chybné ID", "Takové ID má již jiný závod.")
            return

        if fileuuid := api.get_basic_info(self.mw.db).get("stages_uuid"):
            pass
        else:
            fileuuid = uuid.uuid4().hex
            api.set_basic_info(self.mw.db, {"stages_uuid": fileuuid})

        with open(fp, "w+") as f:
            json.dump({"mode": 0, "stages": [{"url": str(self.mw.db.url), "uuid": fileuuid}]}, f)

        self._show()

    def _stage_clicked(self, item: QListWidgetItem):
        match self.mode:
            case StageClickMode.NONE:
                pass
            case StageClickMode.DELETE:
                self.stages_list.takeItem(self.stages_list.row(item))
                del item
                self._save()
                self._show()
        self.mode = StageClickMode.NONE

    def _delete_enable(self):
        self.mode = StageClickMode.DELETE

    def _save(self):
        mode = int(self.basic_radio.isChecked())
        stages = []
        for item in [self.stages_list.item(i) for i in range(self.stages_list.count())]:
            eng = create_engine(item.data(Qt.UserRole))
            fileuuid = api.get_basic_info(eng).get("stages_uuid")
            if not fileuuid:
                fileuuid = uuid.uuid4().hex
                api.set_basic_info(eng, {"stages_uuid": fileuuid})
            stages.append({"url": item.data(Qt.UserRole), "uuid": fileuuid})
        with open(self.file, "w+") as f:
            json.dump({"mode": mode, "stages": stages}, f)

    def _get_html_event(self):
        stages = []
        for item in [self.stages_list.item(i) for i in range(self.stages_list.count())]:
            eng = create_engine(item.data(Qt.UserRole))
            bi = api.get_basic_info(eng)
            stages.append(
                {"name": bi.get("name"), "date": parser().parse(bi.get("date_tzero")).strftime("%d. %m. %Y, %H:%M"),
                 "limit": bi.get("limit"), "band": bi["band"]})
        return {"id": Path(self.file).stem, "stages": stages}

    def calculate(self, db):
        self._show()
        if not self.stages_list.count():
            QMessageBox.warning(self, "Chyba", "Nejsou přidány žádné etapy.")
            return ""

        races = [self.stages_list.item(i).data(Qt.UserRole) for i in range(self.stages_list.count())]

        headers = []

        runners = {}
        default = [None for _ in races]

        for e, race in enumerate(races):
            headers.append(f"E{e + 1}")
            try:
                db = sqlalchemy.create_engine(race, max_overflow=-1)
                sess = Session(db)
                categories = sess.scalars(Select(Category)).all()

                for category in categories:
                    res = results.calculate_category(db, category.name)
                    for result in res:
                        key = (result.reg or result.name)
                        if key not in runners.keys():
                            runners[key] = default.copy()
                        runners[key][e] = (category.name, result.place, result.time, result.tx,
                                           result.status, result.name)
                sess.close()

            except:
                QMessageBox.warning(self, "Chyba",
                                    f"Nepodařilo se načíst a zpracovat závod {race}. Nebude v etapových výsledkách")

        dsq_without_ok_result = []
        dsq_multiple_categories = []

        cats = {}
        for runner in runners.keys():
            if None in runners[runner] or 0 in map(lambda x: x[1], runners[runner]):
                name = None
                for res in runners[runner]:
                    if res:
                        name = res[5]
                        break
                if name:
                    dsq_without_ok_result.append(name)
                continue

            person_cats = list(set(map(lambda x: x[0], runners[runner])))

            if len(person_cats) != 1:
                dsq_multiple_categories.append(runners[runner][0][5])
                continue

            cat = person_cats[0]
            if cat not in cats.keys():
                cats[cat] = [runners[runner]]
            else:
                cats[cat].append(runners[runner])

        cats_results = {}
        for cat in cats.keys():
            res = []
            for runner in cats[cat]:
                res.append((runner[0][5], sum(map(lambda x: x[1], runner)),
                            (-sum(map(lambda x: x[3], runner)), sum(map(lambda x: x[2], runner)), runner[0][5]),
                            runner))
            cats_results[cat] = sorted(res, key=lambda x: x[1] if self.basic_radio.isChecked() else x[2])

        categories = []
        for cat_res in cats_results.keys():
            runners = []
            last_res = None
            last_place = 0
            for i, res in enumerate(cats_results[cat_res]):
                if (res[1] if self.basic_radio.isChecked() else res[2][:2]) != last_res:
                    last_place = i + 1
                    last_res = res[1] if self.basic_radio.isChecked() else res[2][:2]
                individual_res = []
                for result in res[3]:
                    individual_res.append(
                        f"{results.format_delta(timedelta(seconds=result[2]))}, {result[3]} TX ({result[1]})")
                runners.append({"place": f"{last_place}.", "name": res[0],
                                "time": results.format_delta(timedelta(seconds=res[2][1])), "tx": f"{-res[2][0]} TX",
                                "places": res[1], "results": [
                        f"{results.format_delta(timedelta(seconds=r[2]))}, {r[3]} TX ({r[1]})" for
                        r in res[3]]})
            categories.append({"name": cat_res, "runners": runners})

        env = Environment(
            loader=FileSystemLoader(Path(__file__).parent.absolute()), autoescape=select_autoescape()
        )

        return env.get_template("results_templ.html").render(
            event=self._get_html_event(), dsq_without_ok_result=sorted(dsq_without_ok_result),
            dsq_multiple_categories=sorted(dsq_multiple_categories), categories=categories,
            method=("Prostý součet umístění" if self.basic_radio.isChecked() else "Součet kontrol a časů")
        )


fileplugin = StagesPlugin
