---
trigger: always_on
---

1. Uso de herramientas de IA
Cualquier herramienta que se cree para entender el contexto del problema o de la solución debe ubicarse exclusivamente dentro de la carpeta:
ia_tools/
No se deben crear herramientas fuera de esa carpeta.
La carpeta ia_tools solo debe tocarse cuando realmente sea necesario crear o modificar herramientas.
2. Manejo de archivos temporales y datos
Si es necesario:
crear archivos de logs
extraer datos desde alguna fuente
generar archivos auxiliares para lectura o análisis
todo eso debe hacerse dentro de una carpeta temporal, por ejemplo:
temp_ia/
Esta carpeta es estrictamente temporal.
Una vez que la tarea esté completada, la carpeta temp_ia debe eliminarse por completo, sin dejar residuos.
3. Modificación de código existente
Al modificar el código del proyecto:
Ignorar la carpeta ia_tools
No revisar, editar ni refactorizar nada dentro de ella
Solo se permite tocar ia_tools si el objetivo explícitamente requiere:
crear nuevas herramientas
modificar herramientas existentes
4. Prioridad y orden mental
Primero: entender el problema usando el código existente.
Segundo: modificar únicamente lo necesario fuera de ia_tools.
Tercero (solo si hace falta): crear o ajustar herramientas dentro de ia_tools.
Limpieza final obligatoria: eliminar cualquier carpeta temporal usada.