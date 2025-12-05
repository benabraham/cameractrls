{
  description = "cameractrls development environment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
        };
      in
      {
        devShells.default = pkgs.mkShell {
          buildInputs = with pkgs; [
            # Python with GTK bindings
            python3
            python3Packages.pygobject3

            # GTK (both 3 and 4 supported)
            gtk3
            gtk4
            gobject-introspection

            # Camera viewer dependencies
            SDL2
            libjpeg_turbo

            # SpaceMouse support (optional)
            libspnav

            # Development tools
            git
          ];

          shellHook = ''
            export LD_LIBRARY_PATH="${pkgs.SDL2}/lib:${pkgs.libjpeg_turbo.out}/lib:${pkgs.libspnav}/lib:$LD_LIBRARY_PATH"
            echo "📷 cameractrls development environment loaded"
            echo ""
            echo "Available commands:"
            echo "  ./cameractrls.py -l         # List camera controls (CLI)"
            echo "  ./cameractrlsgtk.py         # GTK3 GUI"
            echo "  ./cameractrlsgtk4.py        # GTK4 GUI"
            echo "  ./cameraview.py             # SDL camera viewer"
            echo "  ./insta360-ctrl.py          # Insta360 Link controls"
            echo ""
          '';
        };
      }
    );
}
