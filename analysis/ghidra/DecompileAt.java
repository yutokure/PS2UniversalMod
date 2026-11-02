// Decompile the functions at the given addresses; create a function (and disassemble) when
// none is defined there.  Usage: DecompileAt <out.c> <hexaddr> ...
// @category PS2Lab
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.listing.Function;
import java.io.PrintWriter;

public class DecompileAt extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        PrintWriter out = new PrintWriter(args[0], "UTF-8");
        DecompInterface ifc = new DecompInterface();
        ifc.openProgram(currentProgram);
        java.util.List<String> addrs = new java.util.ArrayList<>();
        for (int i = 1; i < args.length; i++)
            for (String s : args[i].split("[,\s]+")) if (!s.isEmpty()) addrs.add(s);
        for (String s : addrs) {
            Address a = currentProgram.getAddressFactory().getDefaultAddressSpace().getAddress(s.trim());
            Function f = currentProgram.getFunctionManager().getFunctionContaining(a);
            if (f == null) {
                new DisassembleCommand(a, null, true).applyTo(currentProgram, monitor);
                f = createFunction(a, null);
            }
            if (f == null) { out.println("/* no function at " + a + " */"); continue; }
            DecompileResults r = ifc.decompileFunction(f, 120, monitor);
            out.println("\n/* === " + f.getEntryPoint() + " " + f.getName() + " === */");
            out.println(r.decompileCompleted() ? r.getDecompiledFunction().getC() : "/* decompile failed */");
        }
        out.close();
    }
}
