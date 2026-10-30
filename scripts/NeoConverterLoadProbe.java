import net.fabricmc.api.EnvType;
import net.fabricmc.loader.api.FabricLoader;
import net.fabricmc.loader.impl.launch.knot.Knot;

/** Isolated acceptance probe: real Knot/game discovery, resolution, and mod class loading. */
public final class NeoConverterLoadProbe {
    public static void main(String[] args) throws Exception {
        boolean expected = Boolean.parseBoolean(args[0]);
        Knot knot = new Knot(EnvType.SERVER);
        ClassLoader gameLoader = knot.init(new String[] {"--gameDir", "."});
        FabricLoader loader = FabricLoader.getInstance();
        boolean actual = loader.isModLoaded("lithium");
        if (actual != expected) throw new AssertionError("Lithium presence " + actual + ", expected " + expected);
        if (expected) {
            Class<?> entrypoint = Class.forName(
                "net.caffeinemc.mods.lithium.fabric.LithiumFabricMod", false, gameLoader
            );
            if (entrypoint.getClassLoader() != gameLoader) {
                throw new AssertionError("Mod entrypoint did not use the game Knot class loader");
            }
            System.out.println("NEOCONVERTER_ACCEPTED lithium=" +
                loader.getModContainer("lithium").get().getMetadata().getVersion() +
                " entrypoint=" + entrypoint.getName() + " namespace=" +
                loader.getMappingResolver().getCurrentRuntimeNamespace());
        } else {
            System.out.println("NEOCONVERTER_REJECTED_ORIGINAL lithium=false");
        }
    }
}
