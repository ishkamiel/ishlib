package SyntaxCheck;

use warnings;
use strict;

use Carp;
use File::Temp qw/tempfile :seekable/;
use Test::More tests => 5;

my @files_to_check = ( 'ishlib.sh' );

sub syntax_check {
    my $fn = shift;
    my $shell = shift;

    system '/usr/bin/env', $shell, '-n', $fn;
    return $?
}

sub shellcheck {
    my $fn = shift;
    my $shell = shift;

    my $output = qx|shellcheck --norc -f tty -s $shell -S style $fn|;
    my $res = $?;
    if ($res != 0) {
        printf STDERR $output;
    }
    return $res;
}

for my $fn (@files_to_check) {
    # Create a temporary sh-only copy of the script
    my $tmp = "$fn.tmp";

    open my $fh_in, '<', $fn or die "Couldn't open $fn for reading: $!";
    open my $fh_out, '>', "$tmp" or die "Couldn open $tmp for writing: $!";

    while (my $line = <$fh_in>)  {   
        print $fh_out $line;
        $line =~ m/^###EOF4SH$/ and last;
    }

    close $fh_out;
    close $fh_in;

    # Run basic syntax checks
    ok(syntax_check($fn, 'bash') == 0, 'syntax check bash');
    ok(syntax_check($fn, 'zsh') == 0, 'syntax check zsh');
    ok(syntax_check($tmp, 'sh') == 0, 'syntax check sh');

    # Run strict shellcheck
    ok(shellcheck($fn, 'bash') == 0, 'shellcheck bash');
    # ok(shellcheck($fn, 'zsh') == 0, 'shellcheck zsh');
    ok(shellcheck($tmp, 'sh') == 0, 'shellcheck sh');

    unlink $tmp
}

1;