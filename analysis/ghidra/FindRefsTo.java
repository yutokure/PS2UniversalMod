// List references (from address, ref type, containing function) to each address range.
// Usage: FindRefsTo <out.txt> <startHex-endHex> ...
// @category PS2Lab
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.ReferenceIterator;
import java.io.PrintWriter;

public class FindRefsTo extends GhidraScript {
    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        PrintWriter out = new PrintWriter(args[0], "UTF-8");
        java.util.List<String> rs = new java.util.ArrayList<>();
        for (int i = 1; i < args.length; i++)
            for (String s : args[i].split("[,\s]+")) if (!s.isEmpty()) rs.add(s);
        for (String r : rs) {
            String[] p = r.split("-");
            Address a = toAddr(p[0]);
            Address e = p.length > 1 ? toAddr(p[1]) : a;
            out.println("# " + r);
            for (Address x = a; x.compareTo(e) <= 0; x = x.add(1)) {
                ReferenceIterator it = currentProgram.getReferenceManager().getReferencesTo(x);
                while (it.hasNext()) {
                    Reference ref = it.next();
                    Function f = currentProgram.getFunctionManager().getFunctionContaining(ref.getFromAddress());
                    out.println(x + " <- " + ref.getFromAddress() + " " + ref.getReferenceType()
                        + " " + (f == null ? "-" : f.getName() + "@" + f.getEntryPoint()));
                }
            }
        }
        out.close();
    }
}
