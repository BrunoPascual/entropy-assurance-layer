import os
from dotenv import load_dotenv
from qiskit import QuantumCircuit, transpile
from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2

load_dotenv()
token = os.getenv("IBM_QUANTUM_TOKEN")

# Salva a conta localmente, sem expor o token no código
QiskitRuntimeService.save_account(channel="ibm_quantum_platform", token=token, overwrite=True)
service = QiskitRuntimeService(channel="ibm_quantum_platform")

backend = service.least_busy(operational=True, simulator=False)
print("Backend escolhido:", backend.name)

qc = QuantumCircuit(1, 1)
qc.h(0)
qc.measure(0, 0)

isa = transpile(qc, backend=backend, optimization_level=1)
sampler = SamplerV2(mode=backend)
job = sampler.run([isa], shots=128)
print("Job enviado. ID:", job.job_id())

result = job.result()
counts = result[0].data.c.get_counts()
print("Resultado:", counts)