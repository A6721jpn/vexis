
import felupe as fem
import numpy as np
import matplotlib.pyplot as plt

def investigate_sed():
    print("FElupe version:", fem.__version__)
    
    # Create simple mesh
    mesh = fem.Rectangle(n=(3,3))
    region = fem.Region(mesh, fem.Quad(), fem.GaussLegendre(order=1, dim=2))
    field = fem.FieldAxisymmetric(region)
    
    # Material
    umat = fem.NeoHooke(mu=1.0, bulk=100.0)
    solid = fem.SolidBody(umat, fem.FieldContainer([field]))
    
    print("\n--- Running Assembly ---")
    try:
        # solid.assemble returns (r, K). It updates results internally?
        res = solid.assemble(prob=None) 
        print("Assembly finished.")
    except Exception as e:
        print("Assembly failed:", e)
        import traceback
        traceback.print_exc()

    if hasattr(solid, "results"):
        print("Solid results attrs:", [x for x in dir(solid.results) if not x.startswith("_")])
        if hasattr(solid.results, "kinematics"):
            print("Kinematics found.")
            F = solid.results.kinematics[0]
            print("F shape:", F.shape)
            
            try:
                # Reshape to (3, 3, -1)
                shape = F.shape # (3, 3, Q, C)
                F_flat = F.reshape(3, 3, -1)
                print("F flattened shape:", F_flat.shape)
                
                W_flat = umat.function(F_flat)
                print("W calculated (flat). Shape:", W_flat.shape) # Should be (Q*C,)
                
                # Reshape back to (Q, C)
                W = W_flat.reshape(shape[2], shape[3])
                print("W reshaped:", W.shape)
                print("Mean W per element:", np.mean(W, axis=0))
            except Exception as e:
                print("Reshape approach failed:", e)
    
if __name__ == "__main__":
    investigate_sed()
