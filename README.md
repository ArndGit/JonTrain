To make apk (ubuntu)

## Prepare Build Env

 git clone https://github.com/kivy/buildozer
 cd buildozer
 python3 setup.py build
 sudo pip install -e .
 
  nano ~/.bashrc
  #append to end
  #export PATH=$PATH:~/.local/bin/
  
  
## Compile apk
   buildozer android debug
   