#!/bin/bash

# Copyright (C) 2018  Lee C. Bussy (@LBussy)

# This file is part of LBussy's BrewPi Script Remix (BrewPi-Script-RMX).
#
# BrewPi Script RMX is free software: you can redistribute it and/or
# modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# BrewPi Script RMX is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with BrewPi Script RMX. If not, see <https://www.gnu.org/licenses/>.

# These scripts were originally a part of brewpi-script, scripts for
# the BrewPi project (https://github.com/BrewPi). Legacy support (for the
# very popular Arduino controller) seems to have been discontinued in
# favor of new hardware.  My original intent was to simply make these
# scripts work again since the original called for PHP5 explicity. I've
# spent so much time making them work and re-writing the logic I'm
# officialy calling it a re-mix.

# All credit for the original concept, as well as the BrewPi project as
# a whole, goes to Elco, Geo, Freeder, vanosg, routhcr, ajt2 and many
# more contributors around the world. Apologies if I have missed anyone.

############
### Init
############

# Set up some project variables
THISSCRIPT="fixPermissions.sh"
VERSION="0.4.5.0"
# These should stay the same
PACKAGE="BrewPi-Script-RMX"

# Support the standard --help and --version.
#
# func_usage outputs to stdout the --help usage message.
func_usage () {
  echo -e "$PACKAGE $THISSCRIPT version $VERSION
Usage: sudo . $THISSCRIPT"
}
# func_version outputs to stdout the --version message.
func_version () {
  echo -e "$THISSCRIPT ($PACKAGE) $VERSION
Copyright (C) 2018 Lee C. Bussy (@LBussy)
This is free software: you can redistribute it and/or modify it
under the terms of the GNU General Public License as published
by the Free Software Foundation, either version 3 of the License,
or (at your option) any later version.
<https://www.gnu.org/licenses/>
There is NO WARRANTY, to the extent permitted by law."
}
if test $# = 1; then
  case "$1" in
    --help | --hel | --he | --h )
      func_usage; exit 0 ;;
    --version | --versio | --versi | --vers | --ver | --ve | --v )
      func_version; exit 0 ;;
  esac
fi

echo -e "\n***Script $THISSCRIPT starting.***\n"

### Check if we have root privs to run
if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root: sudo ./$THISSCRIPT" 1>&2
   exit 1
fi

############
### Functions to catch/display errors during setup
############
warn() {
  local fmt="$1"
  command shift 2>/dev/null
  echo -e "$fmt\n" "${@}"
  echo -e "\n*** ERROR ERROR ERROR ERROR ERROR ***\n----------------------------------\nSee above lines for error message\nScript NOT completed\n"
}

die () {
  local st="$?"
  warn "$@"
  exit "$st"
}

# the script path will one dir above the location of this bash file
unset CDPATH
myPath="$( cd "$( dirname "${BASH_SOURCE[0]}")" && pwd )"
scriptPath="$(dirname "$myPath")"
webPath="/var/www"

echo -e "\n***** Fixing file permissions for $webPath *****"
sudo chown -R www-data:www-data "$webPath"||warn
sudo chmod -R g+rwx "$webPath"||warn
sudo find "$webPath" -type d -exec chmod g+rwxs {} \;||warn

echo -e "\n***** Fixing file permissions for $scriptPath *****"
sudo chown -R brewpi:brewpi "$scriptPath"||warn
sudo chmod -R g+rwx "$scriptPath"||warn
sudo find "$scriptPath" -type d -exec chmod g+s {} \;||warn

