from qiskit import QuantumCircuit
from qiskit.quantum_info import Statevector

# 1. Cria um circuito quântico com 2 qubits
qc = QuantumCircuit(2)

# 2. Aplica uma porta Hadamard no qubit 0 e uma porta CNOT usando o qubit 0 como controle
qc.h(0)
qc.cx(0, 1)

# 3. Calcula o vetor de estado para verificar se está funcionando
state = Statevector.from_instruction(qc)

print("✅ Qiskit funcionando perfeitamente!")
print("\nCircuito Criado:")
print(qc.draw(output="text"))
print("\nEstado Final Quântico:")
print(state)
