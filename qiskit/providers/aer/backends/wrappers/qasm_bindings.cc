#include <pybind11/pybind11.h>

#include "simulators/qasm/qasm_controller.hpp"
#include "simulators/controller_execute.hpp"

#include "framework/json.hpp"

PYBIND11_MODULE(qasm_controller_wrapper, m) {
    m.def("qasm_controller_execute", &AER::controller_execute<AER::Simulator::QasmController>, "instance of controller_execute for QasmController");
    m.def("qasm_controller_execute_new", [](const py::object &qobj) -> py::object {
        return AER::controller_execute_new<AER::Simulator::QasmController>(qobj);
    });
}
