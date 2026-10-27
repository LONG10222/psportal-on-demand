# Load only a mapping of YAML primitives. Never instantiate YAML objects.
require 'yaml'
source, target, port, controller, dns, lan = ARGV
secret = STDIN.read
raise 'missing configuration' unless File.file?(source) && File.size(source) <= 32*1024*1024
config = YAML.safe_load(File.read(source), permitted_classes: [], permitted_symbols: [], aliases: true)
raise 'configuration must be a map' unless config.is_a?(Hash)
config['port']=Integer(port)
config['socks-port']=0
config['mixed-port']=0
config['redir-port']=0
config['tproxy-port']=0
config['allow-lan']=false
config['bind-address']='127.0.0.1'
config['external-controller']=(secret.empty? ? '127.0.0.1' : lan)+':'+controller
config.delete('external-controller-tls')
config.delete('external-controller-unix')
config.delete('external-controller-pipe')
config['secret']=secret
config['tun']={'enable'=>false}
config['sniffer']={'enable'=>false}
config['ipv6']=false
config['routing-mark']=6666
config['dns']=(config['dns'].is_a?(Hash) ? config['dns'] : {}).merge({
  'enable'=>true, 'listen'=>'127.0.0.1:18753', 'enhanced-mode'=>'redir-host', 'ipv6'=>false,
  'default-nameserver'=>[dns], 'proxy-server-nameserver'=>[dns]})
config['dns']['nameserver']=[dns] unless config['dns']['nameserver'].is_a?(Array) && !config['dns']['nameserver'].empty?
File.open(target, File::WRONLY|File::CREAT|File::TRUNC, 0600) {|f| f.write(YAML.dump(config)) }
